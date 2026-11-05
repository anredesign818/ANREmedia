# Retired 04.11.2026: Telegram posts now go out automatically from GitHub Actions
# (.github/workflows/telegram.yml + tg/queue.json, log in tg/posted.json).
# This stub posts nothing, so old reminders cannot create duplicates.
print('ok: True — публикация в Telegram теперь идёт автоматически через GitHub Actions '
      '(tg/queue.json). Ничего делать не нужно, этот скрипт больше ничего не публикует.')
