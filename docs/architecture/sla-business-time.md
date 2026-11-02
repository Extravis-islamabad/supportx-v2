# SLA business time: the published case table

REQ-SLA-014 asks for one business-time service whose results are covered by a published table of
at least 50 cases. This is that table. `backend/app/modules/sla/tests/test_business_time_table.py`
reads it and checks every row against `app/modules/sla/domain/calendar.py`, so a change to the
maths that breaks a row fails CI. Add a row whenever a bug is found.

## Rules the table pins

- A calendar is a working week in one IANA time zone, plus holidays.
- A period whose end is not after its start crosses midnight (22:00-06:00 is one continuous
  period, REQ-SLA-014 AC3). It belongs to the day it **starts** on, so a holiday or a missing
  weekday removes the whole night.
- Each period becomes real time on its own date, so daylight saving is right on the day it
  changes: a 22:00-06:00 night is 7 hours on a spring-forward night and 9 hours on a fall-back
  night.
The rules marked **(rule: ...)** are product choices, confirmed by the product owner on
2026-11-02. Each lives in one place in the code and has named cases here, so a change is one
function plus its rows.

- **(rule: special date-range hours)** a calendar may hold other hours for a date range (Ramadan
  09:00-14:00, a Friday prayer break 12:30-14:00). Inside the range its own week replaces the
  normal week: a break is the gap between two periods, a weekday without periods is closed.
  Precedence: holiday > special date-range hours > weekly schedule; a half day halves the
  range's hours. Ranges on one calendar never overlap (refused, `exception_ranges_overlap`);
  code: `Calendar._week_on`.

- **(rule: holiday by start date)** see the second bullet above; code: `Calendar.day_intervals`.
- **(rule: daylight-saving gap)** a local time inside a spring-forward gap takes the offset from
  before the change (02:30 becomes 03:30); code: `Calendar._local_instant`.
- **(rule: half day)** a half day keeps the first half of the day's working time (`afternoon`
  off, the default choice); `morning` off keeps the second half. It takes the first or second half of that day's
  **working time**: 09:00-18:00 splits at 13:30; 08:00-12:00 + 13:00-17:00 splits at the lunch break; code: `_half`.
- Adding time that ends exactly at the end of a period gives that end (17:00), never the next
  morning. Adding zero gives the start itself, even outside working hours.
- A period's start is working time, its end is not.
- "Around the clock" counts every second.

## Calendars

Week syntax: days (`Mon-Fri`, `Sun-Thu`, `Sun`), then periods, several separated by commas;
groups separated by `;`. Holidays are a date, optionally followed by `morning` or `afternoon`.
Special hours: `first..last: week` (the same week syntax); several ranges separated by ` + `.

| Code | Time zone | Week | Holidays | Special hours |
|---|---|---|---|---|
| K-MF | Asia/Karachi | Mon-Fri 09:00-18:00 | 2026-02-05; 2026-03-23; 2026-08-14; 2026-12-24 afternoon; 2026-12-25 | |
| R-ST | Asia/Riyadh | Sun-Thu 08:00-17:00 | | |
| L-SPLIT | Europe/London | Mon-Fri 08:00-12:00, 13:00-17:00 | 2026-12-24 morning; 2026-12-25; 2026-12-28 | |
| NY-NIGHT | America/New_York | Mon-Sun 22:00-06:00 | | |
| K-NIGHT | Asia/Karachi | Mon-Fri 22:00-06:00 | | |
| K-MS | Asia/Karachi | Mon-Sat 09:00-18:00 | | |
| U-LEAP | UTC | Mon-Fri 09:00-17:00 | | |
| ATC | UTC | around the clock | | |
| K-HALF | Asia/Karachi | Mon-Fri 09:00-18:00 | 2026-11-04 morning; 2026-11-05 afternoon | |
| U-LATE | UTC | Mon-Fri 16:00-24:00 | | |
| U-SUNNIGHT | UTC | Sun 20:00-02:00 | | |
| NY-NIGHT-H | America/New_York | Mon-Sun 22:00-06:00 | 2026-11-03 | |
| NY-GAP | America/New_York | Sun 02:30-05:00 | | |
| K-RAM | Asia/Karachi | Mon-Fri 09:00-18:00 | 2027-03-01; 2027-02-11 afternoon | 2027-02-08..2027-03-09: Mon-Thu 09:00-14:00; Fri 09:00-12:30, 14:00-15:00 |
| K-MID | Asia/Karachi | Mon-Fri 09:00-18:00 | | 2027-02-10..2027-02-11: Wed-Thu 10:00-12:00 |

## Cases

Times are local to the calendar's zone. `add` adds business time to **From**; `between` counts
business time from **From** to **To**; `working` says whether **From** is business time.

| # | Calendar | Check | From | Amount or to | Expected | Why |
|---|---|---|---|---|---|---|
| 1 | K-MF | add | 2026-11-02 10:00 | 2h | 2026-11-02 12:00 | inside one day |
| 2 | K-MF | add | 2026-11-02 17:00 | 2h | 2026-11-03 10:00 | rolls to the next morning |
| 3 | K-MF | add | 2026-11-06 17:00 | 2h | 2026-11-09 10:00 | skips the weekend |
| 4 | K-MF | add | 2026-11-07 12:00 | 1h | 2026-11-09 10:00 | starts on a Saturday |
| 5 | K-MF | add | 2026-11-02 07:00 | 30m | 2026-11-02 09:30 | starts before opening |
| 6 | K-MF | add | 2026-11-02 16:00 | 2h | 2026-11-02 18:00 | ends exactly at closing |
| 7 | K-MF | add | 2026-11-02 18:00 | 1m | 2026-11-03 09:01 | starts exactly at closing |
| 8 | K-MF | add | 2026-11-02 09:00 | 9h | 2026-11-02 18:00 | one business day |
| 9 | K-MF | add | 2026-11-02 09:00 | 45h | 2026-11-06 18:00 | one business week |
| 10 | K-MF | add | 2026-11-02 09:00 | 0 | 2026-11-02 09:00 | zero |
| 11 | K-MF | add | 2026-11-07 10:00 | 0 | 2026-11-07 10:00 | zero outside hours stays put |
| 12 | K-MF | add | 2026-02-04 17:00 | 2h | 2026-02-06 10:00 | skips a Thursday holiday |
| 13 | K-MF | add | 2026-03-20 17:00 | 2h | 2026-03-24 10:00 | weekend then a Monday holiday |
| 14 | K-MF | add | 2026-08-13 17:30 | 1h | 2026-08-17 09:30 | Friday holiday then weekend |
| 15 | K-MF | add | 2026-12-24 10:00 | 4h | 2026-12-28 09:30 | rule: half day; afternoon off, holiday, weekend |
| 16 | K-MF | between | 2026-11-02 08:00 | 2026-11-02 19:00 | 9h | only the open hours count |
| 17 | K-MF | between | 2026-11-06 17:00 | 2026-11-09 10:00 | 2h | across a weekend |
| 18 | K-MF | between | 2026-11-02 09:00 | 2026-11-09 09:00 | 45h | one calendar week |
| 19 | K-MF | between | 2026-11-09 10:00 | 2026-11-06 17:00 | -2h | reversed is negative |
| 20 | K-MF | between | 2026-11-07 00:00 | 2026-11-08 23:00 | 0 | a weekend has none |
| 21 | K-MF | working | 2026-11-02 09:00 | - | yes | opening minute counts |
| 22 | K-MF | working | 2026-11-02 18:00 | - | no | closing minute does not |
| 23 | K-MF | working | 2026-11-07 12:00 | - | no | Saturday |
| 24 | K-MF | working | 2026-03-23 12:00 | - | no | holiday |
| 25 | R-ST | add | 2026-11-05 16:00 | 2h | 2026-11-08 09:00 | REQ-SLA-010 AC1 |
| 26 | R-ST | add | 2026-11-06 10:00 | 1h | 2026-11-08 09:00 | starts on a Friday |
| 27 | R-ST | add | 2026-11-08 08:00 | 9h | 2026-11-08 17:00 | a full Sunday |
| 28 | R-ST | between | 2026-11-05 12:00 | 2026-11-08 12:00 | 9h | across Friday and Saturday |
| 29 | R-ST | working | 2026-11-06 10:00 | - | no | Friday |
| 30 | R-ST | working | 2026-11-08 10:00 | - | yes | Sunday |
| 31 | L-SPLIT | add | 2026-11-02 11:00 | 2h | 2026-11-02 14:00 | over the lunch break |
| 32 | L-SPLIT | add | 2026-11-02 12:30 | 30m | 2026-11-02 13:30 | starts in the lunch break |
| 33 | L-SPLIT | between | 2026-11-02 08:00 | 2026-11-02 17:00 | 8h | REQ-SLA-010 AC2: two periods |
| 34 | L-SPLIT | working | 2026-11-02 12:30 | - | no | lunch break |
| 35 | L-SPLIT | add | 2026-03-27 16:00 | 2h | 2026-03-30 09:00 | over the spring change |
| 36 | L-SPLIT | between | 2026-03-27 16:00 | 2026-03-30 09:00 | 2h | spring change, business time intact |
| 37 | L-SPLIT | add | 2026-10-23 16:00 | 2h | 2026-10-26 09:00 | over the autumn change |
| 38 | L-SPLIT | add | 2026-12-23 16:00 | 2h | 2026-12-24 14:00 | rule: half day; morning off: afternoon only |
| 39 | L-SPLIT | add | 2026-12-24 16:00 | 2h | 2026-12-29 09:00 | two holidays and a weekend |
| 40 | L-SPLIT | between | 2026-12-24 00:00 | 2026-12-25 00:00 | 4h | rule: half day; half day of a split day |
| 41 | NY-NIGHT | between | 2026-03-07 21:00 | 2026-03-08 07:00 | 7h | spring-forward night is shorter |
| 42 | NY-NIGHT | between | 2026-10-31 21:00 | 2026-11-01 07:00 | 9h | fall-back night is longer |
| 43 | NY-NIGHT | between | 2026-11-01 21:00 | 2026-11-02 07:00 | 8h | an ordinary night |
| 44 | NY-NIGHT | add | 2026-03-07 22:00 | 7h | 2026-03-08 06:00 | the whole short night |
| 45 | NY-NIGHT | add | 2026-10-31 22:00 | 8h | 2026-11-01 05:00 | the long night has an hour left |
| 46 | NY-NIGHT | working | 2026-11-02 03:00 | - | yes | Sunday's night shift |
| 47 | NY-NIGHT | working | 2026-11-02 12:00 | - | no | daytime |
| 48 | NY-NIGHT | add | 2026-11-02 12:00 | 1h | 2026-11-02 23:00 | waits for the night |
| 49 | NY-NIGHT | add | 2026-11-02 23:00 | 4h | 2026-11-03 03:00 | REQ-SLA-014 AC3: continuous over midnight |
| 50 | K-NIGHT | working | 2026-11-07 03:00 | - | yes | Friday's night runs into Saturday |
| 51 | K-NIGHT | working | 2026-11-08 03:00 | - | no | no Saturday night shift |
| 52 | K-NIGHT | add | 2026-11-06 23:00 | 8h | 2026-11-09 23:00 | Friday night, then Monday night |
| 53 | K-NIGHT | working | 2026-11-02 03:00 | - | no | no Sunday night shift |
| 54 | K-NIGHT | between | 2026-11-02 00:00 | 2026-11-07 12:00 | 40h | five nights |
| 55 | K-MS | add | 2026-11-06 17:00 | 2h | 2026-11-07 10:00 | Saturday is a working day |
| 56 | K-MS | add | 2026-11-07 17:00 | 2h | 2026-11-09 10:00 | Sunday is not |
| 57 | U-LEAP | add | 2028-02-28 16:00 | 2h | 2028-02-29 10:00 | into a leap day |
| 58 | U-LEAP | add | 2028-02-29 16:00 | 2h | 2028-03-01 10:00 | out of a leap day |
| 59 | U-LEAP | between | 2027-12-31 16:00 | 2028-01-03 10:00 | 2h | over a year boundary |
| 60 | U-LEAP | add | 2026-12-31 16:30 | 1h | 2027-01-01 09:30 | New Year's Day is not a holiday here |
| 61 | ATC | add | 2026-11-07 23:00 | 2h | 2026-11-08 01:00 | every second counts |
| 62 | ATC | between | 2026-03-07 21:00 | 2026-03-08 07:00 | 10h | no daylight saving in UTC |
| 63 | K-HALF | working | 2026-11-04 12:00 | - | no | rule: half day; morning off |
| 64 | K-HALF | working | 2026-11-04 14:00 | - | yes | rule: half day; afternoon works (from 13:30) |
| 65 | K-HALF | working | 2026-11-05 13:00 | - | yes | rule: half day; morning works (to 13:30) |
| 66 | K-HALF | working | 2026-11-05 14:00 | - | no | rule: half day; afternoon off |
| 67 | K-HALF | add | 2026-11-03 17:00 | 2h | 2026-11-04 14:30 | rule: half day; next day opens at 13:30 |
| 68 | K-HALF | between | 2026-11-04 00:00 | 2026-11-06 00:00 | 9h | rule: half day; two half days |
| 69 | U-LATE | add | 2026-11-02 23:00 | 2h | 2026-11-03 17:00 | a period ending at midnight |
| 70 | U-LATE | working | 2026-11-03 00:00 | - | no | midnight is the end, not working |
| 71 | U-SUNNIGHT | working | 2026-11-09 01:00 | - | yes | Sunday night into Monday |
| 72 | U-SUNNIGHT | add | 2026-11-07 12:00 | 7h | 2026-11-15 21:00 | one night a week |
| 73 | K-MF | add | 2026-11-02 09:00 | 27h | 2026-11-04 18:00 | three business days |
| 74 | NY-NIGHT-H | working | 2026-11-03 03:00 | - | yes | rule: holiday by start date; Monday's night runs into the holiday |
| 75 | NY-NIGHT-H | working | 2026-11-03 23:00 | - | no | rule: holiday by start date; the night that starts on the holiday is off |
| 76 | NY-NIGHT-H | between | 2026-11-03 00:00 | 2026-11-04 07:00 | 6h | rule: holiday by start date; only Monday night's last six hours |
| 77 | NY-GAP | between | 2026-03-07 12:00 | 2026-03-08 12:00 | 1h 30m | rule: daylight-saving gap; 02:30 does not exist, so the period starts 03:30 |
| 78 | NY-GAP | between | 2026-03-14 12:00 | 2026-03-15 12:00 | 2h 30m | rule: daylight-saving gap; an ordinary Sunday |
| 79 | NY-GAP | working | 2026-03-08 03:00 | - | no | rule: daylight-saving gap; before the shifted start |
| 80 | K-RAM | working | 2027-02-08 13:00 | - | yes | rule: special date-range hours; inside the range's hours |
| 81 | K-RAM | working | 2027-02-08 15:00 | - | no | rule: special date-range hours; the range closes at 14:00 |
| 82 | K-RAM | working | 2027-02-05 15:00 | - | yes | rule: special date-range hours; the Friday before the range keeps the normal week |
| 83 | K-RAM | working | 2027-02-12 13:00 | - | no | rule: special date-range hours; Friday prayer break |
| 84 | K-RAM | between | 2027-02-12 00:00 | 2027-02-13 00:00 | 4h 30m | rule: special date-range hours; a Friday with a break |
| 85 | K-RAM | add | 2027-02-12 14:30 | 2h | 2027-02-15 10:30 | rule: special date-range hours; over a weekend inside the range |
| 86 | K-RAM | between | 2027-03-01 00:00 | 2027-03-02 00:00 | 0 | rule: special date-range hours; a holiday beats the range |
| 87 | K-RAM | working | 2027-03-01 10:00 | - | no | rule: special date-range hours; holiday inside the range |
| 88 | K-RAM | between | 2027-02-11 00:00 | 2027-02-12 00:00 | 2h 30m | rule: special date-range hours; a half day halves the range's hours |
| 89 | K-RAM | add | 2027-02-05 16:00 | 4h | 2027-02-08 11:00 | rule: special date-range hours; an SLA that starts before the range ends inside it |
| 90 | K-RAM | between | 2027-03-09 00:00 | 2027-03-10 00:00 | 5h | rule: special date-range hours; the range's last day (a Tuesday) |
| 91 | K-RAM | between | 2027-03-10 00:00 | 2027-03-11 00:00 | 9h | rule: special date-range hours; the day after, the normal week again |
| 92 | K-MID | between | 2027-02-08 00:00 | 2027-02-13 00:00 | 31h | rule: special date-range hours; a range from Wednesday to Thursday |
| 93 | K-MID | working | 2027-02-10 15:00 | - | no | rule: special date-range hours; mid-week range closes at 12:00 |
