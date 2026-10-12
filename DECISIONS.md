# DECISIONS.md

**Indexes.** At startup I create `uq_employees_emp_code` to enforce the employee business key; `ix_employees_department_emp_code` for department filtering and sorted employee listing; `ix_employees_joined_department` for join-date and headcount work; `uq_attendance_emp_date` to allow at most one record per employee per attendance date and protect punch-in races; `ix_attendance_date_emp` for date ordering and range scans; `ix_attendance_status_date_emp` for status-filtered date queries; and `ix_attendance_emp_punch_in` to find the latest eligible punch-in. I rejected a separate attendance `emp_code` index because it duplicates the leading-key capability of `uq_attendance_emp_date`.

**Punch-in race.** Both requests attempt the insert. The unique compound index lets one win. The other raises `DuplicateKeyError`, converted to HTTP 409; uniqueness is not decided by a check-then-insert.

**Ties.** The leaderboard uses standard competition ranking on total late minutes, then filters `rank <= limit`. Everyone tied at the cutoff rank is returned, sorted by total late minutes descending and employee code ascending.

**Headcount.** The department summary starts from eligible employees, then looks up logs. Employees with no matching logs remain in the result, rather than being lost by starting from attendance.

**At 100x.** I would measure representative workloads and consider cursor-based pagination plus precomputed monthly summaries for expensive analytics.
