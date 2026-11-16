---
name: anticaptcha
description: CAPTCHA solving API service. Use this skill when you need to solve CAPTCHAs programmatically via HTTP API. Supports reCAPTCHA v2/v3, hCaptcha, Turnstile, Yandex SmartCaptcha, slider and image-to-text CAPTCHA.
---

# AntiCAPTCHA API Service

HTTP API для решения CAPTCHA. Задача создаётся запросом `POST /api/v1/task`,
воркер решает её в фоне, результат забирается опросом `GET /api/v1/task/{task_id}`.

## Base URL

```
https://anticaptcha.your-domain.com
```

Или для локальной разработки:
```
http://localhost:8000
```

Все эндпоинты API — под префиксом `/api/v1` (`ANTICAPTCHA_API_PREFIX`).

## Authentication

Токен передаётся в заголовке:
```
Authorization: Bearer <token>
```

| Эндпоинт | Токен |
|---|---|
| `POST /api/v1/task`, `GET /api/v1/task/{task_id}` | только API ключ клиента (`ac_...`); admin token не принимается |
| `POST /api/v1/user` | `ANTICAPTCHA_ADMIN_TOKEN` или API ключ пользователя-админа |
| `POST /api/v1/api-key/{user_id}` | admin token или ключ админа — для любого пользователя; ключ обычного пользователя — только для себя |
| `GET /api/v1/api-keys/{user_id}` | то же правило: свой `user_id` или админ |
| `GET /api/v1/stats`, `GET /health`, `GET /` | без авторизации |

Нет заголовка, неверный формат или неизвестный токен — `401`; чужой `user_id` или
не-админ на `POST /api/v1/user` — `403`.

### Получить ключ

Регистрации нет: пользователей создаёт только админ.

```bash
# Создать пользователя (только админ). Ответ: {"id": 2, "username": "myuser", ...}
curl -X POST $BASE_URL/api/v1/user \
  -H "Authorization: Bearer $ANTICAPTCHA_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username": "myuser", "password": "mypassword"}'

# Выпустить API ключ пользователю id=2 (тела нет; ключ показывается один раз)
curl -X POST $BASE_URL/api/v1/api-key/2 \
  -H "Authorization: Bearer $ANTICAPTCHA_ADMIN_TOKEN"
# Ответ: {"id": 1, "key": "ac_xxxx...", "is_active": true, "created_at": "..."}

# Список ключей пользователя (поле key всегда "***hidden***")
curl $BASE_URL/api/v1/api-keys/2 \
  -H "Authorization: Bearer $ANTICAPTCHA_ADMIN_TOKEN"
```

То же без HTTP, внутри контейнера API (пишет прямо в базу, admin token не нужен):

```bash
python -m app.cli create-user myuser mypassword [--admin]
python -m app.cli create-key myuser
python -m app.cli list-keys myuser
python -m app.cli revoke-key --id 7        # или --user myuser
python -m app.cli delete-user myuser --yes
```

## Quick Start

### 1. Создать задачу (reCAPTCHA v2)

```bash
curl -X POST $BASE_URL/api/v1/task \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "recaptcha_v2",
    "input_data": {
      "site_key": "6Le...",
      "page_url": "https://example.com"
    }
  }'
```

**Ответ:**
```json
{"task_id": 123, "status": "pending"}
```

### 2. Получить результат

```bash
curl $BASE_URL/api/v1/task/123 \
  -H "Authorization: Bearer $API_KEY"
```

```json
{
  "task_id": 123,
  "status": "solved",
  "result": {"token": "03AGdBq26..."},
  "error": null,
  "created_at": "2026-11-05T10:00:00",
  "solved_at": "2026-11-05T10:00:05"
}
```

## API Endpoints

### POST /api/v1/task
Создать задачу на решение CAPTCHA.

**Request:**
```json
{
  "type": "recaptcha_v2",
  "input_data": {"site_key": "6Le...", "page_url": "https://example.com"}
}
```

Оба поля обязательны. `type` — один из типов ниже, иначе `422`. Поля
`input_data` зависят от типа (см. «Поля `input_data`»); их проверяет воркер, а не
API: ошибка в них даёт задачу со статусом `failed` и текстом в `error`.

**Response:** `{"task_id": <int>, "status": "pending"}`

Ошибки: `401` — нет/неверный ключ; `413` — тело больше
`ANTICAPTCHA_MAX_BODY_BYTES` (по умолчанию 5 MiB); `422` — неизвестный `type`
или нет обязательного поля; `429` — у ключа уже
`ANTICAPTCHA_MAX_ACTIVE_TASKS_PER_KEY` задач в `pending`/`processing`
(по умолчанию 20, `0` — без лимита).

### GET /api/v1/task/{task_id}
Статус и результат задачи. Видны только задачи, созданные этим же API ключом;
чужая или несуществующая — `404`.

**Response:**
```json
{
  "task_id": 123,
  "status": "solved",
  "result": {"token": "03AGdBq26..."},
  "error": null,
  "created_at": "2026-11-05T10:00:00",
  "solved_at": "2026-11-05T10:00:05"
}
```

`status`: `pending`, `processing`, `solved`, `failed`. У `failed` в `error` —
текст исключения солвера (например, `Task timed out after 120.0s`), `result` пуст.

Форма `result` по типам:

| Тип | `result` |
|---|---|
| `recaptcha_v2`, `recaptcha_v3`, `hcaptcha`, `turnstile`, `yandex_smartcaptcha` | `{"token": "..."}` |
| `image_text` | `{"text": "..."}` (пустая строка, если OCR ничего не нашёл) |
| `slider` | `{"success": true}` — токена нет; неудача даёт `failed` |

### POST /api/v1/user, POST /api/v1/api-key/{user_id}, GET /api/v1/api-keys/{user_id}
Управление пользователями и ключами — см. «Authentication».

### GET /api/v1/stats
Без авторизации:
```json
{
  "total_tasks": 100,
  "solved_tasks": 95,
  "failed_tasks": 5,
  "pending_tasks": 0,
  "success_rate": 95.0,
  "average_solve_time_seconds": 2.5
}
```

### GET /health
`{"status": "healthy"}`. `GET /` возвращает `{"service": "anticaptcha", "status": "running", "version": "..."}`.

Swagger UI — `/docs`, ReDoc — `/redoc`.

## Поддерживаемые типы CAPTCHA

| `type` | Описание | Замечания |
|-----|----------|-------------------|
| `recaptcha_v2` | Google reCAPTCHA v2 (checkbox + картинки) | картиночный челлендж решается только с vision LLM; на реальных сайтах с датацентрового IP успех не гарантирован |
| `recaptcha_v3` | Google reCAPTCHA v3 (invisible) | токен выдаётся, score назначает Google |
| `hcaptcha` | hCaptcha | только поток чекбокса; интерактивный image-челлендж не поддерживается |
| `turnstile` | Cloudflare Turnstile | |
| `yandex_smartcaptcha` | Yandex SmartCaptcha | с датацентрового IP нужен резидентный `proxy`; силуэты не решаются |
| `slider` | Слайдер-CAPTCHA (AliExpress, Alibaba и др.) | нужен только `page_url`; токена нет |
| `image_text` | Текст на картинке (OCR) | |

Других типов API не принимает (`POST /task` → 422); подробности и состояние
каждого типа — таблица «Типы задач» в README.md.

### Поля `input_data`

Браузерные типы (`recaptcha_v2`, `recaptcha_v3`, `hcaptcha`, `turnstile`,
`yandex_smartcaptcha`):

| Поле | Обязательно | Описание |
|---|---|---|
| `site_key` | да | 1–100 символов из `[A-Za-z0-9_-]` |
| `page_url` | да | страница с виджетом; `http`/`https`, loopback и приватные адреса отвергаются (SSRF-guard) |
| `render_mode` | нет | `page` (по умолчанию) или `widget` — воркер не грузит сайт, а подставляет страницу с виджетом провайдера (когда сайт закрыт от IP воркера WAF-ом) |
| `action` | нет | только `recaptcha_v3`, по умолчанию `submit` |
| `proxy` | нет | только `yandex_smartcaptcha`: `scheme://[user:pass@]host:port`, `http`/`https`/`socks5` (SOCKS5 без логина) |

`slider`: `page_url` (обязательно, тот же SSRF-guard), опционально
`handle_selector` и `track_selector` (строка или список строк CSS-селекторов).

`image_text`: `image` — картинка в base64 (без префикса `data:`), форматы PNG,
JPEG, WEBP, BMP; не больше `ANTICAPTCHA_MAX_IMAGE_PIXELS` (4 000 000) пикселей и
`ANTICAPTCHA_MAX_IMAGE_SIDE` (4096) по стороне.

## Примеры для Claude/Codex

### Пример 1: Решить reCAPTCHA v2 и дождаться токена

```bash
# 1. Создать задачу
TASK_ID=$(curl -fsS -X POST $BASE_URL/api/v1/task \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "recaptcha_v2",
    "input_data": {"site_key": "6Le...", "page_url": "https://example.com/login"}
  }' | jq -r '.task_id')

# 2. Ждать результата
while true; do
  RESULT=$(curl -fsS $BASE_URL/api/v1/task/$TASK_ID \
    -H "Authorization: Bearer $API_KEY")
  STATUS=$(echo "$RESULT" | jq -r '.status')

  if [ "$STATUS" = "solved" ]; then
    TOKEN=$(echo "$RESULT" | jq -r '.result.token')
    echo "Solved! Token: $TOKEN"
    break
  elif [ "$STATUS" = "failed" ]; then
    echo "Failed: $(echo "$RESULT" | jq -r '.error')"
    exit 1
  fi

  sleep 2
done

# 3. Использовать токен
curl -X POST https://example.com/login \
  -d "username=user&password=pass&g-recaptcha-response=$TOKEN"
```

### Пример 2: hCaptcha

```bash
curl -X POST $BASE_URL/api/v1/task \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "hcaptcha",
    "input_data": {"site_key": "...", "page_url": "https://example.com/register"}
  }'
```

### Пример 3: Cloudflare Turnstile в режиме «виджет»

```bash
curl -X POST $BASE_URL/api/v1/task \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "turnstile",
    "input_data": {
      "site_key": "0x4AAAA...",
      "page_url": "https://example.com/",
      "render_mode": "widget"
    }
  }'
```

### Пример 4: Текстовая CAPTCHA по картинке

```bash
curl -X POST $BASE_URL/api/v1/task \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"type\": \"image_text\", \"input_data\": {\"image\": \"$(base64 -w0 captcha.png)\"}}"
# result: {"text": "..."}
```

### Пример 5: Python

```python
import time
import requests

BASE_URL = "https://anticaptcha.your-domain.com"
API_KEY = "ac_..."
HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def solve_captcha(task_type, input_data, timeout=180):
    """Создать задачу и вернуть её result (dict)"""
    r = requests.post(
        f"{BASE_URL}/api/v1/task",
        headers=HEADERS,
        json={"type": task_type, "input_data": input_data},
    )
    r.raise_for_status()
    task_id = r.json()["task_id"]

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = requests.get(f"{BASE_URL}/api/v1/task/{task_id}", headers=HEADERS)
        r.raise_for_status()
        task = r.json()
        if task["status"] == "solved":
            return task["result"]
        if task["status"] == "failed":
            raise RuntimeError(f"Failed: {task['error']}")
        time.sleep(2)
    raise TimeoutError(f"task {task_id} not finished in {timeout}s")


token = solve_captcha(
    "recaptcha_v2",
    {"site_key": "6Le...", "page_url": "https://example.com/login"},
)["token"]
print(f"Token: {token}")
```

### Пример 6: JavaScript/Node.js

```javascript
const BASE_URL = 'https://anticaptcha.your-domain.com';
const API_KEY = 'ac_...';
const headers = { Authorization: `Bearer ${API_KEY}`, 'Content-Type': 'application/json' };

async function solveCaptcha(type, inputData) {
  const created = await fetch(`${BASE_URL}/api/v1/task`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ type, input_data: inputData }),
  });
  if (!created.ok) throw new Error(`create: HTTP ${created.status}`);
  const { task_id } = await created.json();

  while (true) {
    const res = await fetch(`${BASE_URL}/api/v1/task/${task_id}`, { headers });
    if (!res.ok) throw new Error(`poll: HTTP ${res.status}`);
    const task = await res.json();
    if (task.status === 'solved') return task.result;
    if (task.status === 'failed') throw new Error(task.error);
    await new Promise(r => setTimeout(r, 2000));
  }
}

solveCaptcha('turnstile', { site_key: '0x4AAAA...', page_url: 'https://example.com' })
  .then(result => console.log('Token:', result.token));
```

## Лимиты

- Активных задач (`pending` + `processing`) на один API ключ —
  `ANTICAPTCHA_MAX_ACTIVE_TASKS_PER_KEY`, по умолчанию 20; сверх — `429`.
- Тело запроса — `ANTICAPTCHA_MAX_BODY_BYTES`, по умолчанию 5 MiB; сверх — `413`.
- Решение одной задачи — `ANTICAPTCHA_TASK_TIMEOUT`, по умолчанию 120 с; по
  истечении задача `failed` с `Task timed out after 120.0s`. У браузерных солверов
  свои, более короткие дедлайны (README, раздел «Типы задач»).
- Готовые задачи удаляются через `ANTICAPTCHA_TASK_RETENTION_DAYS` (7 дней),
  `input_data` — раньше, через `ANTICAPTCHA_INPUT_RETENTION_HOURS` (1 ч).

## Troubleshooting

### Задача не решается
```bash
# Статус и текст ошибки
curl $BASE_URL/api/v1/task/$TASK_ID \
  -H "Authorization: Bearer $API_KEY"

# Здоровье сервиса
curl $BASE_URL/health
```

### Неверный API ключ
Отдельного эндпоинта проверки ключа нет. Запрос несуществующей задачи с ключом
отвечает `401`, если ключ неверный или отозван, и `404`, если ключ рабочий:
```bash
curl -s -o /dev/null -w '%{http_code}\n' $BASE_URL/api/v1/task/0 \
  -H "Authorization: Bearer $API_KEY"
```

### Высокая нагрузка
```bash
# Счётчики задач (без авторизации)
curl $BASE_URL/api/v1/stats
```
`429` на `POST /task` — у ключа исчерпана квота активных задач: дождитесь
завершения уже созданных.

## Ресурсы

- **GitHub:** https://github.com/stufently/anticaptcha
- **Документация:** README.md, DOCKER_COMPOSE.md
