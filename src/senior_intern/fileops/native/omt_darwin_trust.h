// Copyright (c) 2026 My Senior Intern contributors

#import <Foundation/Foundation.h>
#include <sys/stat.h>

int omt_trusted_path_stat(
    NSString *path,
    struct stat *output
);
