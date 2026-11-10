# Anticaptcha Service

Локальный сервис для решения CAPTCHA с использованием ML моделей. Альтернатива внешним сервисам типа anti-captcha.com и capmonster.cloud.

## Возможности

- **reCAPTCHA v2/v3** — решение Google reCAPTCHA
- **hCaptcha** — решение hCaptcha
- **Image-to-text** — классические текстовые CAPTCHA через OCR
- **Cloudflare Turnstile** — решение Turnstile

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