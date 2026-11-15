# Vision LLM - Результаты тестирования и план развития

## Результаты сравнения моделей (2026-11-06)

### Тесты на synthetic CAPTCHA (4 изображения)

| Модель | Success Rate | Avg Time | Примечания |
|--------|--------------|----------|------------|
| **kimi-k2.5** | **50%** (2/4) | 35.0s | Лучшая модель, видит объекты |
| qwen-plus | 0% (0/4) | 25.0s | Не видит объекты |
| qwen-max | 0% (0/4) | 34.7s | Не видит объекты |
| qwen-turbo | 0% (0/4) | 23.6s | Не видит объекты |

### Детали тестов:

**kimi-k2.5** (лучшая):
- ✅ car: `[0-8]` - нашёл машину
- ❌ bicycle: `[]` - правильно (геометрические фигуры)
- ✅ bus: `[3,4,5]` - интерпретировал прямоугольник
- ❌ truck: `[]` - правильно (геометрические фигуры)

**Вывод**: kimi-k2.5 - лучшая модель для CAPTCHA. Она понимает, что synthetic изображения содержат геометрические фигуры, а не реальные объекты.

### Стоимость и скорость:

- **kimi-k2.5**: ~35 сек на challenge, best accuracy
- **qwen-turbo**: ~24 сек, но 0% accuracy
- **Рекомендация**: использовать kimi-k2.5 для production

## План поддержки разных типов CAPTCHA

### Приоритет 1: Текущие

- ✅ **Google reCAPTCHA v2** (уже реализовано)
  - Image challenges
  - 3x3, 4x4 grids

### Приоритет 2: Яндекс

- **Яндекс CAPTCHA**
  - Image selection
  - Slider puzzles
  - Audio challenges

- **Яндекс SmartCaptcha**
  - Text input
  - Image recognition
  - Behavioral analysis

### Приоритет 3: Международные

- **hCaptcha**
  - Image classification
  - Similar to reCAPTCHA

- **Cloudflare Turnstile**
  - Behavioral analysis
  - JavaScript challenges

- **VK Captcha**
  - Text recognition
  - Image puzzles

### Архитектура для мульти-CAPTCHA:

```
workers/solvers/
├── base.py           # Base solver class
├── recaptcha.py      # Google reCAPTCHA v2/v3
├── yandex.py         # Яндекс CAPTCHA
├── yandex_smart.py   # Яндекс SmartCaptcha
├── hcaptcha.py       # hCaptcha
├── cloudflare.py     # Cloudflare Turnstile
└── vk.py             # VK Captcha

workers/classifiers/
├── vision_llm.py     # Vision LLM classifier (универсальный)
├── text_ocr.py       # Text recognition
└── audio_stt.py      # Speech-to-text
```

## Следующие шаги:

1. **Улучшить vision_llm.py** (на основе ревью Codex/Claude)
2. **Протестировать на реальных CAPTCHA** (не synthetic)
3. **Добавить поддержку Яндекс CAPTCHA**
4. **Добавить поддержку hCaptcha**
5. **Оптимизировать скорость** (parallel processing, caching)

## Ожидаемые результаты:

- **Success rate на реальных CAPTCHA**: 70-90%
- **Время решения**: 20-40 сек
- **Поддерживаемые типы**: reCAPTCHA, Яндекс, hCaptcha, Cloudflare, VK