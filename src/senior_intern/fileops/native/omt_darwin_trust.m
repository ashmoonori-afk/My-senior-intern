// Copyright (c) 2026 My Senior Intern contributors

#import "omt_darwin_trust.h"

#include <errno.h>
#include <membership.h>
#include <sys/acl.h>
#include <sys/mount.h>
#include <unistd.h>

static int omt_has_mutation_permission(acl_entry_t entry) {
    acl_permset_t permissions;
    if (acl_get_permset(entry, &permissions) != 0) {
        return -1;
    }
    const acl_perm_t mutation_permissions[] = {
        ACL_WRITE_DATA,
        ACL_APPEND_DATA,
        ACL_DELETE,
        ACL_DELETE_CHILD,
        ACL_WRITE_ATTRIBUTES,
        ACL_WRITE_EXTATTRIBUTES,
        ACL_WRITE_SECURITY,
        ACL_CHANGE_OWNER,
    };
    for (
        size_t index = 0;
        index < sizeof(mutation_permissions) / sizeof(mutation_permissions[0]);
        index++
    ) {
        int result = acl_get_perm_np(
            permissions,
            mutation_permissions[index]
        );
        if (result != 0) {
            return result;
        }
    }
    return 0;
}

static int omt_acl_principal_is_trusted(
    acl_entry_t entry,
    uid_t trusted_uid
) {
    uuid_t *qualifier = acl_get_qualifier(entry);
    if (qualifier == NULL) {
        return -1;
    }
    id_t identifier = 0;
    int identifier_type = -1;
    int result = mbr_uuid_to_id(
        *qualifier,
        &identifier,
        &identifier_type
    );
    acl_free(qualifier);
    if (result != 0) {
        return -1;
    }
    if (identifier_type == ID_TYPE_UID) {
        return identifier == 0 || identifier == trusted_uid;
    }
    return identifier_type == ID_TYPE_GID && identifier == 0;
}

static int omt_has_untrusted_write_acl(
    const char *path,
    uid_t trusted_uid
) {
    acl_t access_list = acl_get_link_np(path, ACL_TYPE_EXTENDED);
    if (access_list == NULL) {
        return -1;
    }
    acl_entry_t entry;
    int result = acl_get_entry(
        access_list,
        ACL_FIRST_ENTRY,
        &entry
    );
    while (result == 0) {
        acl_tag_t tag;
        if (acl_get_tag_type(entry, &tag) != 0) {
            acl_free(access_list);
            return -1;
        }
        if (tag == ACL_EXTENDED_ALLOW) {
            int mutates = omt_has_mutation_permission(entry);
            if (mutates < 0) {
                acl_free(access_list);
                return -1;
            }
            if (mutates == 1) {
                int trusted = omt_acl_principal_is_trusted(
                    entry,
                    trusted_uid
                );
                if (trusted < 0) {
                    acl_free(access_list);
                    return -1;
                }
                if (trusted == 0) {
                    acl_free(access_list);
                    return 1;
                }
            }
        }
        result = acl_get_entry(
            access_list,
            ACL_NEXT_ENTRY,
            &entry
        );
    }
    int final_errno = errno;
    acl_free(access_list);
    return result == -1 && final_errno == EINVAL ? 0 : -1;
}

static int omt_root_is_read_only(void) {
    struct statfs filesystem;
    return statfs("/", &filesystem) == 0
        && (filesystem.f_flags & MNT_RDONLY) != 0;
}

int omt_trusted_path_stat(
    NSString *path,
    struct stat *output
) {
    if (
        path == nil
        || output == NULL
        || !path.isAbsolutePath
        || [path containsString:@"//"]
        || (path.length > 1 && [path hasSuffix:@"/"])
    ) {
        return -1;
    }
    NSArray<NSString *> *components = path.pathComponents;
    NSString *current = @"/";
    uid_t trusted_uid = geteuid();
    struct stat root_stat;
    if (lstat("/", &root_stat) != 0) {
        return -2;
    }
    if (S_ISLNK(root_stat.st_mode)) {
        return -3;
    }
    if (
        omt_has_untrusted_write_acl("/", trusted_uid) != 0
        && !omt_root_is_read_only()
    ) {
        return -4;
    }
    if (root_stat.st_uid != 0 && root_stat.st_uid != trusted_uid) {
        return -5;
    }
    if ((root_stat.st_mode & (S_IWGRP | S_IWOTH)) != 0) {
        return -6;
    }
    if (!S_ISDIR(root_stat.st_mode)) {
        return -7;
    }
    *output = root_stat;
    for (NSUInteger index = 0; index < components.count; index++) {
        NSString *component = components[index];
        if ([component isEqualToString:@"/"]) {
            continue;
        }
        if (
            [component isEqualToString:@"."]
            || [component isEqualToString:@".."]
        ) {
            return -1;
        }
        current = [current stringByAppendingPathComponent:component];
        struct stat current_stat;
        const char *current_path = current.fileSystemRepresentation;
        if (lstat(current_path, &current_stat) != 0) {
            return -11;
        }
        if (S_ISLNK(current_stat.st_mode)) {
            return -12;
        }
        if (
            omt_has_untrusted_write_acl(
                current_path,
                trusted_uid
            ) != 0
        ) {
            return -13;
        }
        if (
            current_stat.st_uid != 0
            && current_stat.st_uid != trusted_uid
        ) {
            return -14;
        }
        if ((current_stat.st_mode & (S_IWGRP | S_IWOTH)) != 0) {
            return -15;
        }
        if (
            index + 1 < components.count
            && !S_ISDIR(current_stat.st_mode)
        ) {
            return -16;
        }
        *output = current_stat;
    }
    return 0;
}
