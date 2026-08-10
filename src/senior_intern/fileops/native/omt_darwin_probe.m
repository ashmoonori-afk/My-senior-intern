// Copyright (c) 2026 My Senior Intern contributors

#import <FileProvider/FileProvider.h>
#import <Foundation/Foundation.h>
#import "omt_darwin_trust.h"

#include <stdint.h>
#include <string.h>
#include <sys/stat.h>

enum {
    OMT_FP_UNKNOWN = -1,
    OMT_FP_NOT_MANAGED = 0,
    OMT_FP_MANAGED = 1,
    OMT_ID_CAPACITY = 512,
    OMT_TEXT_CAPACITY = 256,
};

typedef struct {
    int32_t is_local;
    int32_t is_ubiquitous;
    int32_t is_placeholder;
    int32_t file_provider_state;
    uint64_t path_st_dev;
    uint64_t path_st_ino;
    uint32_t path_st_mode;
    uint32_t object_resource_length;
    uint32_t volume_resource_length;
    char volume_uuid[OMT_TEXT_CAPACITY];
    char volume_identifier[OMT_TEXT_CAPACITY];
    uint8_t object_resource_id[OMT_ID_CAPACITY];
    uint8_t volume_resource_id[OMT_ID_CAPACITY];
} OMTDarwinUrlInfo;

static int omt_copy_text(NSString *value, char *output, size_t capacity) {
    if (value == nil || output == NULL || capacity == 0) {
        return -1;
    }
    if (![value getCString:output maxLength:capacity encoding:NSUTF8StringEncoding]) {
        return -1;
    }
    return output[0] == '\0' ? -1 : 0;
}

static NSData *omt_identity_data(id value) {
    if (value == nil) {
        return nil;
    }
    if ([value isKindOfClass:[NSData class]]) {
        return (NSData *)value;
    }
    if ([value isKindOfClass:[NSString class]]) {
        return [(NSString *)value dataUsingEncoding:NSUTF8StringEncoding];
    }
    NSError *error = nil;
    NSData *archived = [NSKeyedArchiver archivedDataWithRootObject:value
                                            requiringSecureCoding:NO
                                                            error:&error];
    if (archived != nil && error == nil) {
        return archived;
    }
    return [[value description] dataUsingEncoding:NSUTF8StringEncoding];
}

static int omt_copy_identity(
    id value,
    uint8_t *output,
    uint32_t *output_length
) {
    NSData *data = omt_identity_data(value);
    if (data == nil || data.length == 0 || data.length > OMT_ID_CAPACITY) {
        return -1;
    }
    memcpy(output, data.bytes, data.length);
    *output_length = (uint32_t)data.length;
    return 0;
}

static int omt_file_provider_state(NSURL *url, uint32_t timeout_ms) {
    if (@available(macOS 11.0, *)) {
        dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
        __block int result = OMT_FP_UNKNOWN;
        [NSFileProviderManager
            getIdentifierForUserVisibleFileAtURL:url
                completionHandler:^(
                    NSFileProviderItemIdentifier itemIdentifier,
                    NSFileProviderDomainIdentifier domainIdentifier,
                    NSError *error
                ) {
                  if (error == nil && itemIdentifier != nil && domainIdentifier != nil) {
                      result = OMT_FP_MANAGED;
                  } else if (
                      error == nil
                      && itemIdentifier == nil
                      && domainIdentifier == nil
                  ) {
                      result = OMT_FP_NOT_MANAGED;
                  } else if (
                      error != nil
                      && [error.domain isEqualToString:NSCocoaErrorDomain]
                      && error.code == NSFileNoSuchFileError
                  ) {
                      result = OMT_FP_NOT_MANAGED;
                  }
                  dispatch_semaphore_signal(semaphore);
                }];
        dispatch_time_t deadline = dispatch_time(
            DISPATCH_TIME_NOW,
            (int64_t)timeout_ms * NSEC_PER_MSEC
        );
        if (dispatch_semaphore_wait(semaphore, deadline) != 0) {
            return OMT_FP_UNKNOWN;
        }
        return result;
    }
    return OMT_FP_UNKNOWN;
}

int omt_darwin_url_inspect(
    int file_descriptor,
    const char *utf8_path,
    uint32_t timeout_ms,
    OMTDarwinUrlInfo *output
) {
    if (
        file_descriptor < 0
        || utf8_path == NULL
        || output == NULL
        || timeout_ms == 0
    ) {
        return -1;
    }
    memset(output, 0, sizeof(*output));
    output->file_provider_state = OMT_FP_UNKNOWN;
    @autoreleasepool {
        struct stat before;
        struct stat after;
        struct stat path_before;
        struct stat path_after;
        if (fstat(file_descriptor, &before) != 0) {
            return -2;
        }
        NSString *path = [NSString stringWithUTF8String:utf8_path];
        int trust_result = omt_trusted_path_stat(path, &path_before);
        if (trust_result != 0) {
            return -300 + trust_result;
        }
        if (
            before.st_dev != path_before.st_dev
            || before.st_ino != path_before.st_ino
            || before.st_mode != path_before.st_mode
        ) {
            return -399;
        }
        NSURL *url = [NSURL fileURLWithPath:path];
        NSArray<NSURLResourceKey> *keys = @[
            NSURLVolumeIsLocalKey,
            NSURLVolumeIdentifierKey,
            NSURLVolumeUUIDStringKey,
            NSURLFileResourceIdentifierKey,
            NSURLIsUbiquitousItemKey,
        ];
        NSError *error = nil;
        NSDictionary<NSURLResourceKey, id> *values =
            [url resourceValuesForKeys:keys error:&error];
        NSNumber *isLocal = values[NSURLVolumeIsLocalKey];
        NSNumber *isUbiquitous = values[NSURLIsUbiquitousItemKey];
        NSString *volumeUUID = values[NSURLVolumeUUIDStringKey];
        id volumeIdentifier = values[NSURLVolumeIdentifierKey];
        id objectIdentifier = values[NSURLFileResourceIdentifierKey];
        if (
            values == nil
            || error != nil
            || isLocal == nil
            || isUbiquitous == nil
            || volumeUUID == nil
            || volumeIdentifier == nil
            || objectIdentifier == nil
        ) {
            return -4;
        }
        output->is_local = isLocal.boolValue ? 1 : 0;
        output->is_ubiquitous = isUbiquitous.boolValue ? 1 : 0;
        if (isUbiquitous.boolValue) {
            error = nil;
            NSString *status = nil;
            if (
                ![url getResourceValue:&status
                                forKey:NSURLUbiquitousItemDownloadingStatusKey
                                 error:&error]
                || status == nil
                || ![status isEqualToString:NSURLUbiquitousItemDownloadingStatusCurrent]
            ) {
                output->is_placeholder = 1;
            }
        }
        if (
            omt_copy_text(volumeUUID, output->volume_uuid, OMT_TEXT_CAPACITY) != 0
            || omt_copy_text(
                [volumeIdentifier description],
                output->volume_identifier,
                OMT_TEXT_CAPACITY
            ) != 0
            || omt_copy_identity(
                objectIdentifier,
                output->object_resource_id,
                &output->object_resource_length
            ) != 0
            || omt_copy_identity(
                volumeIdentifier,
                output->volume_resource_id,
                &output->volume_resource_length
            ) != 0
        ) {
            return -5;
        }
        output->file_provider_state =
            omt_file_provider_state(url, timeout_ms);
        if (output->file_provider_state == OMT_FP_UNKNOWN) {
            return -6;
        }
        trust_result = omt_trusted_path_stat(path, &path_after);
        if (trust_result != 0) {
            return -700 + trust_result;
        }
        if (
            before.st_dev != path_after.st_dev
            || before.st_ino != path_after.st_ino
            || before.st_mode != path_after.st_mode
        ) {
            return -8;
        }
        if (fstat(file_descriptor, &after) != 0) {
            return -9;
        }
        if (
            before.st_dev != after.st_dev
            || before.st_ino != after.st_ino
            || before.st_mode != after.st_mode
        ) {
            return -10;
        }
        output->path_st_dev = (uint64_t)before.st_dev;
        output->path_st_ino = (uint64_t)before.st_ino;
        output->path_st_mode = (uint32_t)before.st_mode;
        return 0;
    }
}
