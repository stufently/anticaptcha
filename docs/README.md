# Anticaptcha Service

> Локальный сервис для решения CAPTCHA с ML моделями

## Описание

Сервис для автоматического решения CAPTCHA разных типов без зависимости от внешних сервисов (anti-captcha.com, capmonster.cloud и т.д.). Использует ML модели и browser automation.

## Поддерживаемые типы CAPTCHA

- reCAPTCHA v2/v3
- hCaptcha
- Image-to-text (OCR)
- Cloudflare Turnstile

## Технологии

- FastAPI + Python
- SQLite
- Playwright (headless browser)
- Yolo (Ultralytics) — классификация изображений
- EasyOCR — распознавание текста

## Требования

- Python 3.11+
- Docker (для запуска)
- GPU опционален (ускоряет ML модели)

## Быстрый старт

```bash
# Через Docker
docker build -t anticaptcha .
docker run -d -p 8000:8000 anticaptcha

# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

## Статус

- ✅ Базовая инфраструктура FastAPI
- ✅ База данных SQLite
- ✅ REST API endpoints
- ✅ Background worker
- ✅ Solvers для всех типов CAPTCHA
- ⚠️ ML модели нужно загрузить/обучить

## Контакты

Владелец: stufently