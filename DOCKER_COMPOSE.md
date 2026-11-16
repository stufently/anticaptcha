# Docker Compose

Локальный запуск AntiCAPTCHA через `docker-compose.yml`: API и воркер — два
контейнера из одного образа, общая база SQLite на томе.

## Сервисы

| Сервис | Контейнер | Команда | Что делает |
|--------|-----------|---------|------------|
| `anticaptcha-api` | `anticaptcha-api` | `uvicorn app.main:app --host 0.0.0.0 --port 8000` | REST API, порт `127.0.0.1:8000` |
| `anticaptcha-worker` | `anticaptcha-worker` | `python -m workers.task_worker` | решает задачи из базы (браузер, OCR, vision LLM) |
| `nginx` (профиль `with-nginx`) | `anticaptcha-nginx` | — | reverse proxy на `anticaptcha-api:8000`, порты 80/443 |

- База — только SQLite: файл `ANTICAPTCHA_DATABASE_PATH=/app/data/anticaptcha.db`
  на именованном томе `anticaptcha-data`, общем для API и воркера. Других
  бэкендов БД код не поддерживает (`app/database.py` строит `sqlite:///...`).
- Воркер — один (`replicas: 1`, фиксированный `container_name`): задачи
  разбирает один процесс, масштабировать его через `--scale` нельзя.
- Каталоги `./app` и `./workers` смонтированы поверх кода образа (`:ro`): правка
  исходников подхватывается рестартом контейнера, без пересборки. Модели (YOLO,
  EasyOCR) и Chromium — внутри образа.
- Воркер не получает `ANTICAPTCHA_ADMIN_TOKEN`: он открывает страницы клиентов в
  браузере, а админ-токен нужен только API (так же сделано в Helm-чарте).

## Быстрый старт

```bash
# Админ-токен для API (bootstrap пользователей) — в .env рядом с compose
echo "ANTICAPTCHA_ADMIN_TOKEN=$(openssl rand -hex 32)" > .env

docker compose build
docker compose up -d
docker compose ps
docker compose logs -f anticaptcha-api anticaptcha-worker
```

```bash
# Health check
curl http://localhost:8000/health

# API документация (Swagger)
open http://localhost:8000/docs

# Создать задачу (пользователь и API ключ — README, «Создание пользователя и API ключа»)
curl -X POST http://localhost:8000/api/v1/task \
  -H "Authorization: Bearer ac_xxxx..." \
  -H "Content-Type: application/json" \
  -d '{
    "type": "recaptcha_v2",
    "input_data": {"site_key": "6Le...", "page_url": "https://example.com"}
  }'

# Ответ: {"task_id": 1, "status": "pending"}; результат — GET /api/v1/task/1
```

Пользователя и ключ можно выпустить и CLI внутри контейнера API:

```bash
docker compose exec anticaptcha-api python -m app.cli create-user myuser 'password'
docker compose exec anticaptcha-api python -m app.cli create-key myuser
```

## Переменные окружения

Все настройки — `app/config.py`, переменные с префиксом `ANTICAPTCHA_`. Файл
`.env` рядом с `docker-compose.yml` compose использует только для подстановки
`${...}`; в контейнеры попадает лишь то, что перечислено в `environment`.
Compose задаёт:

| Переменная | Значение в compose |
|------------|--------------------|
| `ANTICAPTCHA_DATABASE_PATH` | `/app/data/anticaptcha.db` |
| `ANTICAPTCHA_MODELS_DIR` | `/app/models` |
| `ANTICAPTCHA_ADMIN_TOKEN` | из `.env` (только API) |
| `BAILIAN_CODING_PLAN_API_KEY` | закомментирована; ключ vision LLM (картиночный челлендж reCAPTCHA v2, текстовое задание SmartCaptcha) |

Остальное (таймаут задачи, квота активных задач на ключ, сроки хранения, лимиты
тела и картинок) работает со значениями по умолчанию из `app/config.py`; смысл
лимитов — `docs/specs/limits.md`. Переопределение — строкой в `environment`
нужного сервиса, например `ANTICAPTCHA_TASK_TIMEOUT=180` воркеру.

## Nginx

```bash
docker compose --profile with-nginx up -d
```

Конфиг — `nginx.conf` (rate limit 100 запросов/мин с IP, `/health` без лимита).
HTTPS-сервер в нём закомментирован: для TLS положите сертификаты в `./ssl`
(монтируется в `/etc/nginx/ssl`) и раскомментируйте блок `listen 443`.

## Управление

```bash
docker compose down              # остановить
docker compose down -v           # остановить и удалить том с базой (ВСЕ данные!)
docker compose restart anticaptcha-worker
docker compose build --no-cache && docker compose up -d --force-recreate   # обновление
docker compose logs --tail=100 anticaptcha-worker
docker stats anticaptcha-api anticaptcha-worker
```

## Backup & Restore

База — один файл SQLite (в режиме WAL рядом лежат `-wal`/`-shm`). Копируйте том
при остановленных контейнерах, иначе копия может быть несогласованной. Имя тома
— `<проект>_anticaptcha-data`, где проект по умолчанию — имя каталога.

```bash
docker compose stop
docker run --rm -v anticaptcha_anticaptcha-data:/data -v "$(pwd)":/backup \
  alpine tar czf /backup/anticaptcha-data-backup.tar.gz -C /data .
docker compose start
```

```bash
docker compose stop
docker run --rm -v anticaptcha_anticaptcha-data:/data -v "$(pwd)":/backup \
  alpine tar xzf /backup/anticaptcha-data-backup.tar.gz -C /data
docker compose start
```

## Безопасность

- API слушает только `127.0.0.1:8000`; nginx публикует 80/443 на всех
  интерфейсах — закройте их firewall-ом, если сервис не должен быть доступен
  снаружи.
- `.env` с `ANTICAPTCHA_ADMIN_TOKEN` и ключом LLM не коммитьте.
- SSRF-guard воркера проверяет только `page_url` задачи; редиректы и запросы
  самой страницы он не видит (README, «Типы задач», поле `page_url`). Compose сеть воркера
  не ограничивает — для изоляции egress используйте Helm-чарт с
  `networkPolicy.enabled: true` или свой firewall.

## Troubleshooting

```bash
docker compose logs anticaptcha-api        # контейнер не стартует
docker compose logs anticaptcha-worker     # воркер: готовность солверов при старте
docker compose config                      # проверить итоговый compose
docker volume ls | grep anticaptcha
```

## Лицензия

MIT
