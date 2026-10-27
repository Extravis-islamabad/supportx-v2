# Breached-password list (WP-039 session 2; REQ-SEC-005 AC3; D-089 D2)

`supportx-breached.txt` is Keycloak's password blacklist (`passwordBlacklist(supportx-breached.txt)`
in the realm's password policy). Keycloak lowercases a new password and refuses it when it is on
this list. It ships with every release and is read offline (never an online service, REQ-SEC-002
AC2), so it works on air-gapped installations.

- **Source:** SecLists, `Passwords/Common-Credentials/Pwdb_top-100000.txt`, commit
  `758fecf4925900dd1bd0a3cba39551d6b4f2da8c` (MIT licence, below).
- **Filter:** printable ASCII only, at least 8 characters (shorter ones fail the length rule
  anyway; the floor is 8), lowercased, duplicates removed, order kept: 46,941 entries.

  ```sh
  LC_ALL=C awk 'length($0)>=8 && $0 !~ /[^ -~]/ { l=tolower($0); if (!(l in seen)) { seen[l]=1; print l } }' \
    Pwdb_top-100000.txt > supportx-breached.txt
  ```

- **A larger list:** an operator may replace the file with a bigger one under the same name
  (Keycloak's `password-blacklists` folder; docs/architecture/identity.md). Keycloak reads it
  when the policy is set or Keycloak starts.

## SecLists licence

MIT License

Copyright (c) 2018 Daniel Miessler

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
