"""
Automated tests for ldap_query.py.

Run from the repository root:
    python3 -m unittest part2.test_ldap_query -v
"""

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import ldap_query as lq


class TestLdapQueryMain(unittest.TestCase):
    def test_main_prints_group_members(self):
        conn = MagicMock()
        stdout = io.StringIO()

        with patch("ldap_query.connect", return_value=conn), \
             patch(
                 "ldap_query.find_group",
                 return_value={
                     "cn": "developers",
                     "gidNumber": "2001",
                     "memberUid": ["bob", "alice"],
                 },
             ), \
             patch(
                 "ldap_query.fetch_user",
                 side_effect=[
                     {
                         "uid": "alice",
                         "cn": "Alice Mwangi",
                         "homeDirectory": "/home/alice",
                     },
                     {
                         "uid": "bob",
                         "cn": "Bob Otieno",
                         "homeDirectory": "/home/bob",
                     },
                 ],
             ), \
             patch("sys.argv", ["ldap_query.py", "developers"]), \
             redirect_stdout(stdout):
            result = lq.main()

        output = stdout.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("Group: developers (gidNumber: 2001)", output)
        self.assertIn("Members:", output)
        self.assertIn("alice | Alice Mwangi | /home/alice", output)
        self.assertIn("bob | Bob Otieno | /home/bob", output)
        conn.unbind.assert_called_once()

    def test_main_returns_1_when_group_missing(self):
        conn = MagicMock()
        stderr = io.StringIO()

        with patch("ldap_query.connect", return_value=conn), \
             patch("ldap_query.find_group", return_value=None), \
             patch("sys.argv", ["ldap_query.py", "phantom"]), \
             redirect_stderr(stderr):
            result = lq.main()

        self.assertEqual(result, 1)
        self.assertIn("Error: group 'phantom' not found in directory.", stderr.getvalue())
        conn.unbind.assert_called_once()

    def test_main_returns_1_when_connection_fails(self):
        stderr = io.StringIO()

        with patch(
            "ldap_query.connect",
            side_effect=lq.ldap3.core.exceptions.LDAPException("bind failed"),
        ), patch("sys.argv", ["ldap_query.py", "developers"]), \
             redirect_stderr(stderr):
            result = lq.main()

        self.assertEqual(result, 1)
        self.assertIn("Error: cannot connect to LDAP server", stderr.getvalue())
