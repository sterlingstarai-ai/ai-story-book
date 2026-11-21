"""Select an owner-controlled gcloud configuration before invoking the CLI."""

import os
from pathlib import Path
import stat


def operator_gcloud_config(config_dir=None):
    home = Path.home()
    location = config_dir if config_dir is not None else os.environ.get(
        "CLOUDSDK_CONFIG", str(home / ".config" / "gcloud")
    )
    path = Path(location)
    if not path.is_absolute() or ".." in path.parts or home not in path.parents:
        raise ValueError("Use a private gcloud configuration under the operator home directory")
    # A different local user must not be able to replace any path component.
    for component in [*reversed(path.parents), path]:
        info = component.lstat()
        if (not stat.S_ISDIR(info.st_mode)
                or info.st_uid not in (0, os.geteuid())
                or info.st_mode & 0o022):
            raise ValueError("Unsafe gcloud configuration directory")
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError("The gcloud configuration must be private to its owner")
    return str(path)
