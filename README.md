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
docker run -d -p 8000:8000 -v $(pwd)/data:/app/data anticaptcha

# Запуск worker (в отдельном контейнере)
docker run -d -v $(pwd)/data:/app/data anticaptcha python -m workers.task_worker
```

### Локально

```bash
# Инициализация базы данных
python init_db.py

# Запуск API
uvicorn app.main:app --reload

# Запуск worker (в отдельном терминале)
python run_worker.py
```

## API Documentation

После запуска откройте:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

## Создание пользователя и API ключа

```bash
# Создать пользователя
curl -X POST http://localhost:8000/api/v1/user \
  -H "Content-Type: application/json" \
  -d '{"username": "myuser", "password": "mypassword"}'

# Сгенерировать API ключ (сохраните ключ!)
curl -X POST http://localhost:8000/api/v1/api-key/1

# Ответ: {"id": 1, "key": "ac_xxxx...", "is_active": true}
```

## Создание задачи

```bash
# Image-to-text CAPTCHA
curl -X POST http://localhost:8000/api/v1/task \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ac_xxxx..." \
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
  -H "X-API-Key: ac_xxxx..."

# Ответ:
{
  "task_id": 1,
  "status": "solved",
  "result": {"text": "CAPTCHA_TEXT"},
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

## Ограничения

- **GPU опционален** — модели работают на CPU (медленнее)
- **Headless браузер** — Playwright работает без GUI
- **До 100 задач/час** — для большего масштаба нужна очередь

## Лицензия

MIT