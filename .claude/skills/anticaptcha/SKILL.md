---
name: anticaptcha
description: CAPTCHA solving API service. Use this skill when you need to solve CAPTCHAs programmatically via HTTP API. Supports reCAPTCHA v2/v3, hCaptcha, Turnstile, VK, GeeTest, FunCaptcha, Amazon WAF, Tencent.
---

# AntiCAPTCHA API Service

HTTP API для автоматического решения CAPTCHA. Сервис развернут в Kubernetes и доступен по API.

## Base URL

```
https://anticaptcha.your-domain.com
```

Или для локальной разработки:
```
http://localhost:8000
```

## Authentication

API ключ передается в заголовке:
```
Authorization: Bearer YOUR_API_KEY
```

Получить ключ:
```bash
# Создать пользователя
curl -X POST $BASE_URL/api/v1/user \
  -H "Content-Type: application/json" \
  -d '{"username": "myuser", "email": "user@example.com"}'

# Получить API ключ
curl -X POST $BASE_URL/api/v1/api-key/{user_id}
```

## Quick Start

### 1. Решить reCAPTCHA v2

```bash
curl -X POST $BASE_URL/api/v1/task \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "captcha_type": "recaptcha_v2",
    "page_url": "https://example.com",
    "site_key": "6Le..."
  }'
```

**Ответ:**
```json
{
  "task_id": "abc123",
  "status": "pending"
}
```

### 2. Получить результат

```bash
curl $BASE_URL/api/v1/task/abc123 \
  -H "Authorization: Bearer YOUR_API_KEY"
```

```json
{
  "task_id": "abc123",
  "status": "completed",
  "result": {
    "token": "03AGdBq26...",
    "type": "recaptcha_v2",
    "solve_time": 4.5
  }
}
```

## API Endpoints

### POST /api/v1/task
Создать задачу на решение CAPTCHA.

**Request:**
```json
{
  "captcha_type": "recaptcha_v2",  // Обязательный
  "page_url": "https://example.com",  // Обязательный
  "site_key": "6Le...",  // Для reCAPTCHA/hCaptcha
  "proxy": "http://user:pass@ip:port"  // Опционально
}
```

**Response:**
```json
{
  "task_id": "abc123",
  "status": "pending"
}
```

### GET /api/v1/task/{task_id}
Получить статус и результат задачи.

**Response:**
```json
{
  "task_id": "abc123",
  "status": "completed",  // pending, processing, completed, failed
  "result": {
    "token": "03AGdBq26...",
    "type": "recaptcha_v2",
    "solve_time": 4.5
  },
  "error": null
}
```

### GET /api/v1/captcha/types
Список поддерживаемых типов CAPTCHA.

### GET /health
Проверка здоровья сервиса.

## Поддерживаемые типы CAPTCHA

| Тип | Описание | Когда использовать |
|-----|----------|-------------------|
| `recaptcha_v2` | Google reCAPTCHA v2 (checkbox + images) | Большинство сайтов |
| `recaptcha_v3` | Google reCAPTCHA v3 (score-based) | Невидимая проверка |
| `hcaptcha` | hCaptcha | Privacy-focused сайты |
| `turnstile` | Cloudflare Turnstile | Cloudflare защита |
| `vk_captcha` | VK CAPTCHA (text/image) | VKontakte |
| `vk_challenge` | VK Challenge (behavior) | VK защита от ботов |
| `geetest` | GeeTest (slide/icon) | Китайские сайты |
| `funcaptcha` | FunCaptcha/Arkose Labs | Игровые сайты |
| `amazon_waf` | Amazon WAF CAPTCHA | AWS сайты |
| `tencent` | Tencent CAPTCHA | Китайские сервисы |
| `simple_captcha` | Text/Math CAPTCHA | Простые сайты |

## Примеры для Claude/Codex

### Пример 1: Решить reCAPTCHA на сайте

**Задача:** Решить reCAPTCHA v2 на https://example.com/login

**Решение:**
```bash
# 1. Создать задачу
TASK_ID=$(curl -s -X POST $BASE_URL/api/v1/task \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "captcha_type": "recaptcha_v2",
    "page_url": "https://example.com/login",
    "site_key": "6Le..."
  }' | jq -r '.task_id')

# 2. Ждать результата
while true; do
  RESULT=$(curl -s $BASE_URL/api/v1/task/$TASK_ID \
    -H "Authorization: Bearer $API_KEY")
  
  STATUS=$(echo $RESULT | jq -r '.status')
  
  if [ "$STATUS" = "completed" ]; then
    TOKEN=$(echo $RESULT | jq -r '.result.token')
    echo "Solved! Token: $TOKEN"
    break
  elif [ "$STATUS" = "failed" ]; then
    echo "Failed: $(echo $RESULT | jq -r '.error')"
    exit 1
  fi
  
  sleep 2
done

# 3. Использовать токен
curl -X POST https://example.com/login \
  -d "username=user&password=pass&g-recaptcha-response=$TOKEN"
```

### Пример 2: Решить hCaptcha

```bash
curl -X POST $BASE_URL/api/v1/task \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "captcha_type": "hcaptcha",
    "page_url": "https://example.com/register",
    "site_key": "..."
  }'
```

### Пример 3: Решить Cloudflare Turnstile

```bash
curl -X POST $BASE_URL/api/v1/task \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "captcha_type": "turnstile",
    "page_url": "https://example.com"
  }'
```

### Пример 4: Python скрипт

```python
import requests
import time

BASE_URL = "https://anticaptcha.your-domain.com"
API_KEY = "your-api-key"

def solve_captcha(captcha_type, page_url, site_key=None):
    """Решить CAPTCHA и вернуть токен"""
    
    # Создать задачу
    payload = {
        "captcha_type": captcha_type,
        "page_url": page_url
    }
    if site_key:
        payload["site_key"] = site_key
    
    response = requests.post(
        f"{BASE_URL}/api/v1/task",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json=payload
    )
    task_id = response.json()["task_id"]
    
    # Ждать результата
    while True:
        result = requests.get(
            f"{BASE_URL}/api/v1/task/{task_id}",
            headers={"Authorization": f"Bearer {API_KEY}"}
        ).json()
        
        if result["status"] == "completed":
            return result["result"]["token"]
        elif result["status"] == "failed":
            raise Exception(f"Failed: {result['error']}")
        
        time.sleep(2)

# Использование
token = solve_captcha(
    "recaptcha_v2",
    "https://example.com/login",
    "6Le..."
)
print(f"Token: {token}")
```

### Пример 5: JavaScript/Node.js

```javascript
const axios = require('axios');

const BASE_URL = 'https://anticaptcha.your-domain.com';
const API_KEY = 'your-api-key';

async function solveCaptcha(captchaType, pageUrl, siteKey = null) {
  // Создать задачу
  const payload = {
    captcha_type: captchaType,
    page_url: pageUrl
  };
  if (siteKey) payload.site_key = siteKey;
  
  const { data: task } = await axios.post(
    `${BASE_URL}/api/v1/task`,
    payload,
    { headers: { Authorization: `Bearer ${API_KEY}` } }
  );
  
  // Ждать результата
  while (true) {
    const { data: result } = await axios.get(
      `${BASE_URL}/api/v1/task/${task.task_id}`,
      { headers: { Authorization: `Bearer ${API_KEY}` } }
    );
    
    if (result.status === 'completed') {
      return result.result.token;
    } else if (result.status === 'failed') {
      throw new Error(result.error);
    }
    
    await new Promise(r => setTimeout(r, 2000));
  }
}

// Использование
solveCaptcha('turnstile', 'https://example.com')
  .then(token => console.log('Token:', token));
```

## Производительность

| Метод | Скорость | Точность | Стоимость |
|-------|----------|----------|-----------|
| YOLO | 0.1-0.3s | 60-70% | Бесплатно |
| Vision LLM | 1-3s | 70-90% | ~$0.003/CAPTCHA |
| Hybrid | ~1.4s | 70-85% | ~$0.002/CAPTCHA |

## Rate Limits

- 100 запросов в минуту на API ключ
- 10 задач в секунду
- Таймаут задачи: 60 секунд

## Error Handling

**Статусы задач:**
- `pending` - задача в очереди
- `processing` - решается
- `completed` - решена успешно
- `failed` - ошибка

**Коды ошибок:**
- `unsupported_type` - тип CAPTCHA не поддерживается
- `timeout` - таймаут решения
- `invalid_params` - неверные параметры
- `rate_limit` - превышен лимит

## Troubleshooting

### Задача не решается
```bash
# Проверить статус
curl $BASE_URL/api/v1/task/$TASK_ID \
  -H "Authorization: Bearer $API_KEY"

# Проверить здоровье сервиса
curl $BASE_URL/health
```

### Неверный API ключ
```bash
# Проверить ключ
curl $BASE_URL/api/v1/user/me \
  -H "Authorization: Bearer $API_KEY"
```

### Высокая нагрузка
```bash
# Проверить очередь задач
curl $BASE_URL/api/v1/stats \
  -H "Authorization: Bearer $API_KEY"
```

## Ресурсы

- **GitHub:** https://github.com/stufently/anticaptcha
- **Документация:** README.md, DOCKER_COMPOSE.md
- **Настройка qw2:** QWEN_SETUP.md
- **Сравнение моделей:** MODEL_COMPARISON.md