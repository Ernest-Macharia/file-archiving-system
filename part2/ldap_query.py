"""
ldap_query.py
=============
Query an OpenLDAP directory for members of a posixGroup.
Prints uid, full name, and home directory for each member.
"""

import sys
import argparse
import ldap3


# Config — matches the provided docker-compose.yml for Part 2

LDAP_URL   = "ldap://localhost:3389"
BIND_DN    = "cn=admin,dc=dewcis,dc=com"
BIND_PW    = "adminpass"
BASE_DN    = "dc=dewcis,dc=com"
GROUPS_OU  = "ou=groups,dc=dewcis,dc=com"
USERS_OU   = "ou=users,dc=dewcis,dc=com"


# LDAP helpers

def connect() -> ldap3.Connection:
    """Open and return an authenticated LDAP connection."""
    server = ldap3.Server(LDAP_URL, get_info=ldap3.ALL)
    conn   = ldap3.Connection(server, user=BIND_DN, password=BIND_PW,
                               auto_bind=True)
    return conn


def find_group(conn: ldap3.Connection, group_name: str) -> dict | None:
    """
    Search ou=groups for a posixGroup with the given cn.
    Returns the entry dict (gidNumber, memberUid list) or None.
    """
    conn.search(
        search_base   = GROUPS_OU,
        search_filter = f"(&(objectClass=posixGroup)(cn={group_name}))",
        search_scope  = ldap3.SUBTREE,
        attributes    = ["cn", "gidNumber", "memberUid"],
    )
    if not conn.entries:
        return None
    entry = conn.entries[0]
    return {
        "cn":        str(entry.cn),
        "gidNumber": str(entry.gidNumber),
        "memberUid": list(entry.memberUid) if entry.memberUid else [],
    }


def fetch_user(conn: ldap3.Connection, uid: str) -> dict | None:
    """
    Fetch a single user entry from ou=users by uid.
    Returns dict with uid, cn, homeDirectory or None if not found.
    """
    conn.search(
        search_base   = USERS_OU,
        search_filter = f"(&(objectClass=posixAccount)(uid={uid}))",
        search_scope  = ldap3.SUBTREE,
        attributes    = ["uid", "cn", "homeDirectory"],
    )
    if not conn.entries:
        return None
    entry = conn.entries[0]
    return {
        "uid":           str(entry.uid),
        "cn":            str(entry.cn),
        "homeDirectory": str(entry.homeDirectory),
    }


# Main

def main() -> int:
    parser = argparse.ArgumentParser(
        description="List members of an LDAP posixGroup with their home directories.",
    )
    parser.add_argument("group", help="Name of the LDAP group to query.")
    args = parser.parse_args()

    # Connect
    try:
        conn = connect()
    except ldap3.core.exceptions.LDAPException as exc:
        print(f"Error: cannot connect to LDAP server at {LDAP_URL}: {exc}",
              file=sys.stderr)
        return 1

    # Step 1: look up the group
    group = find_group(conn, args.group)
    if group is None:
        print(f"Error: group '{args.group}' not found in directory.",
              file=sys.stderr)
        conn.unbind()
        return 1

    print(f"Group: {group['cn']} (gidNumber: {group['gidNumber']})")
    print("Members:")

    if not group["memberUid"]:
        print("  (no members)")
        conn.unbind()
        return 0

    # Step 2: fetch each member's user entry
    for uid in sorted(group["memberUid"]):
        user = fetch_user(conn, uid)
        if user:
            print(f"  {user['uid']} | {user['cn']} | {user['homeDirectory']}")
        else:
            print(f"  {uid} | (user entry not found in directory)")

    conn.unbind()
    return 0


if __name__ == "__main__":
    sys.exit(main())
