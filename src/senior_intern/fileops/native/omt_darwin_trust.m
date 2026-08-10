// Copyright (c) 2026 My Senior Intern contributors

#import "omt_darwin_trust.h"

#include <sys/acl.h>
#include <unistd.h>

static int omt_has_allow_acl(const char *path) {
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
    while (result == 1) {
        acl_tag_t tag;
        if (acl_get_tag_type(entry, &tag) != 0) {
            acl_free(access_list);
            return -1;
        }
        if (tag == ACL_EXTENDED_ALLOW) {
            acl_free(access_list);
            return 1;
        }
        result = acl_get_entry(
            access_list,
            ACL_NEXT_ENTRY,
            &entry
        );
    }
    acl_free(access_list);
    return result < 0 ? -1 : 0;
}

int omt_trusted_path_stat(
    NSString *path,
    struct stat *output
) {
    if (
        path == nil
        || output == NULL
        || !path.isAbsolutePath
        || ![path.stringByStandardizingPath isEqualToString:path]
    ) {
        return -1;
    }
    NSArray<NSString *> *components = path.pathComponents;
    NSString *current = @"/";
    uid_t trusted_uid = geteuid();
    struct stat root_stat;
    if (
        lstat("/", &root_stat) != 0
        || S_ISLNK(root_stat.st_mode)
        || omt_has_allow_acl("/") != 0
        || (root_stat.st_uid != 0 && root_stat.st_uid != trusted_uid)
        || (root_stat.st_mode & (S_IWGRP | S_IWOTH)) != 0
        || !S_ISDIR(root_stat.st_mode)
    ) {
        return -1;
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
        if (
            lstat(current_path, &current_stat) != 0
            || S_ISLNK(current_stat.st_mode)
            || omt_has_allow_acl(current_path) != 0
            || (
                current_stat.st_uid != 0
                && current_stat.st_uid != trusted_uid
            )
            || (current_stat.st_mode & (S_IWGRP | S_IWOTH)) != 0
            || (
                index + 1 < components.count
                && !S_ISDIR(current_stat.st_mode)
            )
        ) {
            return -1;
        }
        *output = current_stat;
    }
    return 0;
}
