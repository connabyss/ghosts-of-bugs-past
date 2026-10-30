# Hand check of the first real runs

Gemma 3 12B, top 12 suspects each, commit 1f18d73. Gemma called 14 ghosts. Each was checked by reading
both commit messages and the changes. "Maybe" means same code and a similar symptom, but nothing in the
messages says the earlier fix failed.

| Repo | Earlier -> later | Gemma | Hand check | Why |
|---|---|---|---|---|
| click | 19fd4d6 -> c353590 | ghost | **real** | later message: "Fix regression introduced in 8.4.0 by #3126 and properly fix #3043" |
| click | d48b59b -> f67c2bb | ghost | maybe | short help truncation fixed again five years later; message doesn't say why |
| click | a25bf13 -> d48b59b | ghost | maybe | same truncation code: "auto truncate short help" then "fix ... max_length" |
| click | fb7f674 -> e4bb120 | ghost | maybe | "rewrapping of options" then "newline wrapping in option help" |
| click | 4fd2fea -> 9caedb9 | ghost | maybe | flag value with a type, then a larger rework of the same rules (#2952, #2788) |
| click | 92c8053 -> b61ec64 | ghost | not | chained-command arguments vs defaults and subcommands (#925, #919) |
| click | 0f71fe7 -> 7d05a59 | ghost | not | the earlier fix caused a different bug (later message names it) |
| requests | f18733d -> 8081d7b | ghost | maybe | session params given as a list (#804), then lists of 2-tuples everywhere (#817) |
| requests | c28da22 -> 6ff6f75 | ghost | maybe | digest auth after redirect, then "fix potential endless 401 loop", same author 10 days later |
| requests | 95911f0 -> 228c5e6 | ghost | not | the iter_lines rewrite caused new whitespace problems |
| requests | 8081d7b -> 9811424 | ghost | not | a refactor that fixes "a few bugs" |
| requests | ab56e4a -> 8081d7b | ghost | not | Python 3 test fix vs #817 |
| requests | a95bfd3 -> 3299771 | ghost | not | elapsed test and #1133 vs a separate issue from #1151 |
| requests | a776e7c -> 6e76ab7 | ghost | not | params support vs IDNA-encoding the whole netloc (#1362) |

Totals: 1 real, 6 maybe, 7 not.
