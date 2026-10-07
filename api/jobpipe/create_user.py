"""Create the reviewer account, or set a new password for it.

Run inside the api container with `make user USERNAME=jie`, or with `python -m jobpipe.create_user jie`.
"""

import argparse
import getpass
import sys
from collections.abc import Callable

from jobpipe import db, repo
from jobpipe.auth import hash_password, normalise_username
from jobpipe.settings import Settings

MIN_PASSWORD_LENGTH = 12


def main(argv: list[str] | None = None, read_password: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description="Create the reviewer account, or set a new password for it.")
    parser.add_argument("username")
    username = normalise_username(parser.parse_args(argv).username)
    if not username or len(username) > 100:
        print("Give a username of 1 to 100 characters.", file=sys.stderr)
        return 1
    password = read_password("Password: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Use at least {MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        return 1
    if read_password("Repeat the password: ") != password:
        print("The passwords do not match.", file=sys.stderr)
        return 1
    with db.connect(Settings().database_url) as conn:
        db.migrate(conn)
        created = repo.save_user(conn, username, hash_password(password))
        conn.commit()
    print(f"Created {username}." if created else f"Set a new password for {username} and cleared any lockout.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
