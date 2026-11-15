# Vision LLM Integration Guide

## Обзор

Мы интегрировали подход конкурентов: **Vision LLM (qw2)** вместо YOLO для классификации CAPTCHA.

## Почему Vision LLM лучше YOLO:

| Aspect | YOLO | Vision LLM |
|--------|------|------------|
| Training | Требует обучения на реальных CAPTCHA | Не требует обучения |
| Accuracy | 0% на реальных CAPTCHA | 80-95% (ожидается) |
| Classes | Только COCO (80 классов) | Любые объекты |
| Context | Не понимает инструкции | Понимает "Select all X" |
| Speed | 50ms per image | 2-5s per challenge (1 API call) |

## Как это работает:

```
1. Делаем screenshot всей CAPTCHA сетки
2. Отправляем в qw2 с инструкцией: "Select all tiles with bicycles"
3. Получаем JSON: [0, 3, 6]
4. Кликаем по плиткам 0, 3, 6
```

**ОДИН вызов API вместо 9-16 вызовов для каждой плитки!**

## Текущий статус:

✅ Создан модуль `workers/classifiers/vision_llm.py`
✅ Интегрирован в `recaptcha.py`
✅ Docker собран

⏳ **Нужно настроить вызов qw2 CLI**

## Настройка qw2 CLI:

### Вариант 1: Прямой вызов CLI

```python
# В vision_llm.py, метод _call_qwen_cli:

cmd = [
    "qw2",
    "--image", str(image_path),
    "--prompt", prompt
]

result = subprocess.run(cmd, capture_output=True, text=True)
```

### Вариант 2: Через API (если qw2 сервер)

```python
import requests

response = requests.post(
    "http://localhost:PORT/api/classify",
    json={
        "image": base64_image,
        "prompt": prompt
    }
)

indices = response.json()["indices"]
```

### Вариант 3: Fallback на OpenAI API

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key="your-key")

response = await client.chat.completions.create(
    model="gpt-4-vision-preview",
    messages=[{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt}
        ]
    }]
)
```

## Что нужно уточнить:

1. **Как вызывать qw2 для изображений?**
   - Команда CLI?
   - API endpoint?
   - Другой способ?

2. **Формат ввода/вывода:**
   - Как передать изображение? (путь к файлу / base64 / URL)
   - Какой формат ответа? (JSON / text)

3. **Конфигурация:**
   - API ключ / endpoint
   - Timeout
   - Retry policy

## Тестирование:

После настройки qw2:

```bash
# 1. Пересобрать Docker
docker build -t anticaptcha:latest .

# 2. Запустить тест
docker run --rm \
  -v "$(pwd)/data:/app/data" \
  anticaptcha:latest \
  python test_multiple_sites.py

# 3. Ожидаемый результат:
# - Vision LLM классифицирует CAPTCHA
# - Success rate: 80-95%
# - One API call per challenge
```

## Файлы:

- `workers/classifiers/vision_llm.py` - Vision LLM classifier
- `workers/solvers/recaptcha.py` - Updated solver with vision LLM
- `COMPETITOR_ANALYSIS.md` - Analysis of competitor approaches

## Следующие шаги:

1. **Уточнить способ вызова qw2** (CLI/API/другое)
2. **Реализовать реальный вызов** в `_call_qwen_cli`
3. **Протестировать** на реальных CAPTCHA
4. **При необходимости:** добавить fallback на YOLO

---

**Готов ответить на вопросы и доработать интеграцию!**