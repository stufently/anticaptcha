# Анализ подходов конкурентов и план реализации

## Что делают конкуренты (OhMyCaptcha):

### Ключевой инсайт:
**Используют Vision LLM (GPT-4V/Qwen) вместо YOLO для CAPTCHA классификации!**

### Архитектура:

```
CAPTCHA изображение → Base64 encoding → Vision LLM API → JSON с индексами → Клик по плиткам
```

### Преимущества перед YOLO:

1. ✅ **Не нужно обучать на CAPTCHA изображениях** - модель уже знает объекты
2. ✅ **Понимает контекст** - может следовать инструкциям "выбери все X"
3. ✅ **Работает с любыми объектами** - не ограничено COCO классами
4. ✅ **Объясняет решения** - можно логировать reasoning

### Подход для разных CAPTCHA:

| CAPTCHA Type | Решение |
|--------------|---------|
| **reCAPTCHA v2** | Audio transcription (озвучивание) |
| **hCaptcha** | Vision LLM классификация плиток |
| **Turnstile** | Auto-pass (низкий risk) |
| **Image tiles** | Vision LLM → JSON с индексами |

## План реализации:

### 1. Vision LLM интеграция (ПРИОРИТЕТ #1)

**Заменить YOLO на OpenAI-compatible vision API:**

```python
from openai import AsyncOpenAI

async def classify_captcha_tiles(image_bytes: bytes, instruction: str) -> list[int]:
    """
    Классифицирует CAPTCHA плитки с помощью Vision LLM

    Returns: [0, 3, 6] - индексы плиток, которые нужно кликнуть
    """
    client = AsyncOpenAI(
        base_url="https://api.openai.com/v1",  # или локальный Qwen
        api_key="your-api-key"
    )

    # Encode image to base64
    b64 = base64.b64encode(image_bytes).decode()
    data_url = f"data:image/png;base64,{b64}"

    # Call vision model
    response = await client.chat.completions.create(
        model="gpt-4-vision-preview",  # или "Qwen/Qwen-VL-Chat"
        temperature=0.05,
        max_tokens=512,
        messages=[
            {
                "role": "system",
                "content": """You are a CAPTCHA classification assistant.
Images are divided into tiles numbered 0-8 (3x3 grid) or 0-15 (4x4 grid).
Return JSON: {"objects": [0, 3, 6]} - indices of tiles containing the target object.
Return ONLY JSON, no explanations."""
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                    {"type": "text", "text": f"Select all tiles with: {instruction}"}
                ]
            }
        ]
    )

    # Parse response
    raw = response.choices[0].message.content
    data = json.loads(extract_json(raw))
    return data.get("objects", [])
```

### 2. Audio transcription для reCAPTCHA v2

**Альтернативный подход для reCAPTCHA:**

```python
async def solve_recaptcha_audio(page) -> str:
    """Решает reCAPTCHA через audio challenge"""
    # 1. Click audio button
    audio_btn = page.frame_locator('iframe[src*="bframe"]').locator('#recaptcha-audio-button')
    await audio_btn.click()

    # 2. Download audio
    audio_src = await page.locator('audio source').get_attribute('src')
    audio_bytes = await download(audio_src)

    # 3. Transcribe with Whisper/GPT-4
    transcript = await transcribe_audio(audio_bytes)

    # 4. Fill response
    await page.fill('#audio-response', transcript)
    await page.click('#recaptcha-verify-button')

    # 5. Extract token
    return await extract_token(page)
```

### 3. Стоимость и модели:

| Model | Cost per 1K tokens | Speed | Quality |
|-------|-------------------|-------|---------|
| **GPT-4V** | $0.01 input, $0.03 output | Medium | Best |
| **GPT-4V-mini** | $0.002 input, $0.006 output | Fast | Good |
| **Qwen-VL-Chat** | Free (local) | Slow | Good |
| **LLaVA** | Free (local) | Medium | Decent |

**Рекомендация:**
- Development: GPT-4V-mini (быстро, дешево)
- Production: Qwen-VL-Chat локально или GPT-4V для качества

### 4. Что нужно сделать:

**Немедленно:**
1. ✅ Добавить OpenAI-compatible client в requirements
2. ✅ Создать `VisionClassifier` класс
3. ✅ Заменить YOLO классификацию на vision model
4. ✅ Добавить fallback на YOLO если API недоступно

**Опционально:**
5. ⏳ Audio transcription для reCAPTCHA v2
6. ⏳ Local Qwen model через vLLM/SGLang
7. ⏳ Caching для повторяющихся challenges

### 5. Ожидаемый результат:

**Текущий: 0% success** (YOLO не работает на реальных CAPTCHA)

**После vision LLM:**
- reCAPTCHA v2: **70-90%** success (audio)
- hCaptcha: **80-95%** success (vision classification)
- Turnstile: **90%+** success (auto-pass)

**Затраты:**
- API costs: ~$0.01-0.03 per CAPTCHA
- Latency: 2-5 seconds per classification
- No training required!

---

## Следующий шаг:

**Выберите вариант:**

1. **Использовать GPT-4V API** (требует OpenAI API key) - быстро, качественно
2. **Локальный Qwen-VL** (требует GPU/CPU) - бесплатно, медленнее
3. **Гибрид: GPT-4V + YOLO fallback** - надежно, с fallback

Какой вариант предпочитаете?