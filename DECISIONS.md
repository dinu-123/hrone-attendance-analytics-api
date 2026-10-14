# DECISIONS.md

**Indexes.** Startup creates eight named indexes: unique `uq_employees_emp_code` for employee identity; `ix_employees_department_emp_code` for department filtering and employee-code ordering; `ix_employees_joined_department` for join-date and headcount queries; unique `uq_attendance_emp_date` for employee/day uniqueness; `ix_attendance_date_emp` for attendance date sorting and range scans; partial `ix_attendance_late_date_emp_partial` for leaderboard scans of positive late minutes; `ix_attendance_status_date_emp` for status/date filtering; and `ix_attendance_emp_punch_in` for latest punch-in lookup. Startup creation is idempotent.

**Punch-in race.** Both requests attempt insertion. The unique employee/date index accepts one; a duplicate-key error becomes HTTP 409 for the other. This avoids an unsafe check-then-insert.

**Ties.** MongoDB competition ranking assigns 1, 2, 2, 4 for tied totals. Filtering occurs after ranking, so every row tied at the cutoff is returned; ties sort by employee code.

**Headcount.** The department summary starts from employees who joined on or before period end, then looks up logs. Eligible employees with no logs remain counted.

**At 100x.** I would profile representative queries, benchmark changing workloads, add cursor-based pagination, and consider precomputed monthly summaries for analytics where freshness requirements permit.
