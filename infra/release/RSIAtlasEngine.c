#include <mach-o/dyld.h>

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int fail(void) {
    fputs("RSIAtlasEngine: embedded Python launch failed\n", stderr);
    return 126;
}

int main(int argc, char *argv[]) {
    uint32_t executable_size = 0;
    if (_NSGetExecutablePath(NULL, &executable_size) != -1 || executable_size == 0) {
        return fail();
    }
    char *unresolved = calloc(executable_size, sizeof(char));
    if (unresolved == NULL || _NSGetExecutablePath(unresolved, &executable_size) != 0) {
        free(unresolved);
        return fail();
    }
    char resolved[PATH_MAX];
    if (realpath(unresolved, resolved) == NULL) {
        free(unresolved);
        return fail();
    }
    free(unresolved);

    const char *suffix = "/Contents/MacOS/RSIAtlasEngine";
    const size_t resolved_length = strlen(resolved);
    const size_t suffix_length = strlen(suffix);
    if (resolved_length <= suffix_length ||
        strcmp(resolved + resolved_length - suffix_length, suffix) != 0) {
        return fail();
    }
    resolved[resolved_length - suffix_length] = '\0';

    char python[PATH_MAX];
    const int written = snprintf(
        python,
        sizeof(python),
        "%s/Contents/Resources/runtime/python/bin/python3",
        resolved
    );
    if (written < 0 || (size_t)written >= sizeof(python)) {
        return fail();
    }
    char resources[PATH_MAX];
    const int resources_written = snprintf(
        resources,
        sizeof(resources),
        "%s/Contents/Resources/app",
        resolved
    );
    if (resources_written < 0 || (size_t)resources_written >= sizeof(resources) ||
        setenv("RSI_ATLAS_RESOURCE_ROOT", resources, 1) != 0) {
        return fail();
    }

    const char *cleared[] = {
        "DYLD_FALLBACK_FRAMEWORK_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_FRAMEWORK_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "PIP_CONFIG_FILE",
        "PIP_INDEX_URL",
        "PIP_REQUIRE_VIRTUALENV",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "UV_PROJECT",
        "VIRTUAL_ENV",
    };
    for (size_t index = 0; index < sizeof(cleared) / sizeof(cleared[0]); ++index) {
        if (unsetenv(cleared[index]) != 0) {
            return fail();
        }
    }
    if (setenv("PYTHONDONTWRITEBYTECODE", "1", 1) != 0 ||
        setenv("PYTHONNOUSERSITE", "1", 1) != 0) {
        return fail();
    }

    const size_t fixed_count = 5;
    char **arguments = calloc((size_t)argc + fixed_count, sizeof(char *));
    if (arguments == NULL) {
        return fail();
    }
    arguments[0] = python;
    arguments[1] = "-I";
    arguments[2] = "-s";
    arguments[3] = "-m";
    arguments[4] = "rsi_atlas_engine";
    for (int index = 1; index < argc; ++index) {
        arguments[index + 4] = argv[index];
    }
    arguments[argc + 4] = NULL;

    execv(python, arguments);
    free(arguments);
    return fail();
}
