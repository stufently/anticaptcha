# Anticaptcha Service

> Локальный сервис для решения CAPTCHA с ML моделями

## Описание

Сервис для автоматического решения CAPTCHA разных типов без зависимости от внешних сервисов (anti-captcha.com, capmonster.cloud и т.д.). Использует ML модели и browser automation.

## Поддерживаемые типы CAPTCHA

- reCAPTCHA v2/v3
- hCaptcha
- Image-to-text (OCR)
- Cloudflare Turnstile
- Yandex SmartCaptcha
- Slider CAPTCHA (перетаскивание ползунка)

Подробности и ограничения по каждому типу — README в корне, «Типы задач».

## Технологии

- FastAPI + Python
- SQLite (единственная поддерживаемая БД)
- Playwright (headless browser)
- Yolo (Ultralytics) — классификация изображений
- EasyOCR — распознавание текста

## Требования

- Python 3.11+
- Docker (для запуска)
- GPU опционален (ускоряет ML модели)

## Быстрый старт

API и воркер — два процесса из одного образа с общей базой SQLite: запуск —
README в корне («Быстрый старт») или `DOCKER_COMPOSE.md`, Kubernetes — `chart/`.
После запуска API: http://localhost:8000, Swagger: http://localhost:8000/docs.

## Статус

- ✅ Базовая инфраструктура FastAPI
- ✅ База данных SQLite
- ✅ REST API endpoints
- ✅ Background worker
- ✅ Solvers для всех типов CAPTCHA
- ✅ Модели YOLO и EasyOCR в образе; своя модель reCAPTCHA — `docs/TRAINING_GUIDE.md`

## Контакты

Владелец: stufently