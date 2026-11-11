# Anticaptcha Service

Локальный сервис для решения CAPTCHA с использованием ML моделей. Альтернатива внешним сервисам типа anti-captcha.com и capmonster.cloud.

## Возможности

- **Image-to-text** — классические текстовые CAPTCHA через OCR (работает)
- **Cloudflare Turnstile**, **hCaptcha**, **reCAPTCHA v3** — браузерные солверы
  на Playwright; проверены на тестовых ключах провайдеров, подробности в
  разделе «Типы задач»
- **reCAPTCHA v2** — чекбокс и картиночный челлендж (кроп плиток, раунды,
  динамическая сетка); челлендж решается только с включённым vision LLM
- Режим «виджет» (`render_mode=widget`) — решает виджет провайдера даже тогда,
  когда сайт клиента закрыт от IP воркера WAF-ом

## Технологии

- **FastAPI** — REST API
- **SQLite** — база данных
- **Playwright** — автоматизация браузера
- **Yolo (Ultralytics)** — классификация изображений
- **EasyOCR** — распознавание текста

## Быстрый старт

### Через Docker (рекомендуется)

```bash
# Сборка
docker build -t anticaptcha .

# Запуск API сервера
docker run -d --name anticaptcha-api -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -e ANTICAPTCHA_ADMIN_TOKEN=your-secret-token \
  anticaptcha

# Запуск worker (в отдельном контейнере)
docker run -d -v $(pwd)/data:/app/data \
  -e ANTICAPTCHA_ADMIN_TOKEN=your-secret-token \
  anticaptcha python -m workers.task_worker
```

### Локально

```bash
# Инициализация базы данных
python init_db.py

# Запуск API
ANTICAPTCHA_ADMIN_TOKEN=your-secret-token uvicorn app.main:app --reload

# Запуск worker (в отдельном терминале)
ANTICAPTCHA_ADMIN_TOKEN=your-secret-token python run_worker.py
```

### Создание первого пользователя и API ключа

Регистрации нет: пользователей создаёт только админ. Первичный выпуск — двумя способами:

- через CLI внутри контейнера (пишет напрямую в базу, admin token не нужен);
- через HTTP API с `Authorization: Bearer <ANTICAPTCHA_ADMIN_TOKEN>` (см. ниже).

```bash
# Создать пользователя: create-user <username> <password> [--admin]
docker exec -it anticaptcha-api python -m app.cli create-user admin password123 --admin

# Выпустить API ключ: create-key <username> (ключ печатается один раз)
docker exec -it anticaptcha-api python -m app.cli create-key admin
```

### Миграция базы данных

Если у вас уже есть база данных со старой схемой (без полей `password_salt` и `is_admin`), необходимо:

1. **Для новой базы**: просто запустите `python init_db.py` - схема создастся автоматически
2. **Для существующей базы**: выполните миграцию вручную:
   ```sql
   ALTER TABLE users ADD COLUMN password_salt VARCHAR(32);
   ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0;
   ```
   Или удалите старую базу и создайте новую: `rm data/anticaptcha.db && python init_db.py`

## API Documentation

После запуска откройте:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

## Авторизация

Все защищённые эндпоинты принимают заголовок `Authorization: Bearer <token>`:

| Эндпоинт | Токен |
|---|---|
| `POST /api/v1/task`, `GET /api/v1/task/{task_id}` | API ключ клиента (`ac_...`); admin token здесь не принимается |
| `POST /api/v1/user` | `ANTICAPTCHA_ADMIN_TOKEN` или API ключ пользователя-админа |
| `POST /api/v1/api-key/{user_id}` | `ANTICAPTCHA_ADMIN_TOKEN` или ключ админа — для любого пользователя; ключ обычного пользователя — только для себя |

Без заголовка или с неверным форматом — `401`; не-админ на `POST /api/v1/user` — `403`.

## Создание пользователя и API ключа (админ)

```bash
# Создать пользователя (только админ)
curl -X POST http://localhost:8000/api/v1/user \
  -H "Authorization: Bearer $ANTICAPTCHA_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username": "myuser", "password": "mypassword"}'

# Ответ: {"id": 2, "username": "myuser", "is_active": true, "created_at": "...", "api_keys": []}

# Выпустить API ключ пользователю с id=2 (ключ показывается один раз — сохраните!)
curl -X POST http://localhost:8000/api/v1/api-key/2 \
  -H "Authorization: Bearer $ANTICAPTCHA_ADMIN_TOKEN"

# Ответ: {"id": 1, "key": "ac_xxxx...", "is_active": true, "created_at": "..."}
```

## Создание задачи

```bash
# Image-to-text CAPTCHA
curl -X POST http://localhost:8000/api/v1/task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ac_xxxx..." \
  -d '{
    "type": "image_text",
    "input_data": {
      "image": "base64_encoded_image_data"
    }
  }'

# Ответ: {"task_id": 1, "status": "pending"}
```

## Типы задач

| `type` | Что делает | Состояние |
|---|---|---|
| `image_text` | текстовая CAPTCHA по картинке (OCR) | работает |
| `turnstile` | Cloudflare Turnstile | работает: non-interactive виджеты и тестовые ключи; интерактивный виджет (ключ `3x00000000000000000000FF`) решается кликом мыши по чекбоксу |
| `hcaptcha` | hCaptcha | работает поток чекбокса (тестовый ключ `10000000-ffff-ffff-ffff-000000000001`); интерактивный image-челлендж не поддерживается — задача падает с `hCaptcha token not received within 20s (interactive challenge is not supported)` |
| `recaptcha_v3` | reCAPTCHA v3 (invisible) | возвращает токен; score назначает Google, гарантий по нему нет |
| `recaptcha_v2` | reCAPTCHA v2 (плитки) | чекбокс работает (проверено тестовым ключом Google); картиночный челлендж решается **только с включённым vision LLM**, а на реальных сайтах с датацентрового IP успех не гарантирован |

Поля `input_data` для браузерных типов:

| Поле | Обязательно | Описание |
|---|---|---|
| `site_key` | да | ключ сайта; 1–100 символов из `[A-Za-z0-9_-]`, иначе задача падает с `ValueError` |
| `page_url` | да | страница с виджетом. Проходит SSRF-guard: loopback, приватные, неразрешимые адреса и схемы кроме http/https отвергаются |
| `render_mode` | нет | `page` (по умолчанию, если поля нет или оно `null`) или `widget` — см. ниже |
| `action` | нет | только для `recaptcha_v3`, по умолчанию `submit` |

### `render_mode`

- `page` — воркер открывает `page_url` и решает виджет на странице клиента.
- `widget` — воркер не грузит сайт клиента: навигация на `page_url`
  перехватывается внутри браузера, и вместо неё отдаётся минимальная страница с
  виджетом провайдера и вашим `site_key`. Домен в запросе к провайдеру остаётся
  прежним. Режим нужен, когда сайт закрыт от IP воркера WAF-ом (публичные
  демо-страницы отвечают датацентру `403`), а скрипты провайдера доступны.

```bash
# Cloudflare Turnstile в режиме «виджет»
curl -X POST http://localhost:8000/api/v1/task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ac_xxxx..." \
  -d '{
    "type": "turnstile",
    "input_data": {
      "site_key": "1x00000000000000000000AA",
      "page_url": "https://example.com/",
      "render_mode": "widget"
    }
  }'

# Ответ: {"task_id": 2, "status": "pending"}
```

Дедлайны браузерных солверов: Turnstile — 30 с на токен (клик по чекбоксу на
8-й, 14-й и 20-й секунде, не больше трёх попыток), hCaptcha — 20 с на токен
после клика по чекбоксу, reCAPTCHA v3 — 5 с на `api.js` самой страницы, затем
15 с на внедрение скрипта и 20 с на `grecaptcha.execute`, reCAPTCHA v2 — 6 с на
токен после клика по чекбоксу, затем до 5 раундов челленджа (на исход каждого
verify — 10 с; в динамической сетке — до 5 проходов кликов). По истечении
дедлайна задача падает с `RuntimeError`, а не висит до общего таймаута воркера.

reCAPTCHA v2: плитки челленджа классифицирует vision LLM, поэтому без
`BAILIAN_CODING_PLAN_API_KEY` солвер откатывается на локальную YOLO-модель,
которая на реальных снимках Google заметно слабее. Датацентровому IP Google
почти всегда отвечает картиночным челленджем и может потребовать несколько
раундов, так что успех на реальном сайте не гарантирован и с ключом. Тестовый
ключ Google `6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI` проходит без челленджа —
именно он проверяет путь «виджет → чекбокс → токен» в e2e.

Проверка на тестовых ключах провайдеров (нужен выход к Cloudflare, hCaptcha,
Google и `example.com`):

```bash
ANTICAPTCHA_E2E=1 python -m pytest tests/test_m3a_e2e.py tests/test_m3b_e2e.py
```

## Получение результата

```bash
# Получить результат задачи
curl -X GET http://localhost:8000/api/v1/task/1 \
  -H "Authorization: Bearer ac_xxxx..."

# Ответ:
{
  "task_id": 1,
  "status": "solved",
  "result": {"text": "CAPTCHA_TEXT"},
  "error": null,
  "created_at": "2026-11-05T10:00:00",
  "solved_at": "2026-11-05T10:00:05"
}
```

## Статистика

```bash
curl http://localhost:8000/api/v1/stats

# Ответ:
{
  "total_tasks": 100,
  "solved_tasks": 95,
  "failed_tasks": 5,
  "pending_tasks": 0,
  "success_rate": 95.0,
  "average_solve_time_seconds": 2.5
}
```

## Структура проекта

```
anticaptcha/
├── app/
│   ├── api/          # REST endpoints
│   ├── models/       # SQLAlchemy модели
│   ├── schemas/      # Pydantic схемы
│   ├── utils/        # Утилиты
│   ├── main.py       # FastAPI приложение
│   ├── config.py     # Настройки
│   └── database.py   # Подключение к БД
├── workers/
│   ├── task_worker.py   # Background worker
│   └── solvers/         # Solvers для CAPTCHA
├── models/           # ML модели (gitignored)
├── tests/            # Тесты
├── data/             # База данных SQLite
├── requirements.txt
├── Dockerfile
└── README.md
```

## Конфигурация

Создайте `.env` файл на основе `.env.example`:

```bash
cp .env.example .env
```

Основные настройки:
- `ANTICAPTCHA_DATABASE_PATH` — путь к базе данных
- `ANTICAPTCHA_HEADLESS` — headless режим браузера
- `ANTICAPTCHA_BROWSER_TIMEOUT` — таймаут браузера (секунды)

## ML Модели

### Yolo для reCAPTCHA/hCaptcha

Для решения image challenge нужен Yolo:

```python
from ultralytics import YOLO

# Скачать предобученную модель
model = YOLO('yolov8n-cls.pt')

# Сохранить в models/
model.save('models/yolov8n-cls.pt')
```

### EasyOCR для text CAPTCHA

Устанавливается автоматически через `requirements.txt`. При первом запуске скачает модели.

## Обучение Custom Модели

### Зачем нужно

Предобученная модель Yolo (yolov8n.pt) работает на COCO датасете (обычные фото), а не на синтетических CAPTCHA изображениях. Это приводит к:
- False positives на CAPTCHA тайлах
- Низким confidence scores
- Ошибкам для reCAPTCHA-специфичных классов (crosswalk, stairs, etc.)

### Решение

Обучить custom модель на реальных CAPTCHA изображениях:

```bash
# 1. Сбор датасета (50+ challenges, ~400-900 изображений)
docker run --rm --user 1002:1002 \
  -v "$(pwd)/data:/app/data" \
  anticaptcha:latest \
  python collect_recaptcha_dataset.py

# 2. Обучение модели (~5-10 минут на CPU)
docker run --rm --user 1002:1002 \
  -v "$(pwd)/data:/app/data" \
  anticaptcha:latest \
  python train_custom_yolo.py

# 3. Обновление solver для использования custom модели
python update_solver_model.py

# 4. Тестирование
docker run --rm anticaptcha:latest python test_multiple_sites.py
```

### Результаты

**До custom обучения:**
- COCO классы (car, bus, etc.): 70-80% success
- reCAPTCHA-специфичные (crosswalk, stairs, etc.): 0-30% success

**После custom обучения:**
- Все классы: 85-95% success

Подробнее см. `TRAINING_PIPELINE.md` и `COMPLETION_STATUS.md`.

## Ограничения

- **GPU опционален** — модели работают на CPU (медленнее)
- **Headless браузер** — Playwright работает без GUI
- **До 100 задач/час** — для большего масштаба нужна очередь

## Лицензия

MIT