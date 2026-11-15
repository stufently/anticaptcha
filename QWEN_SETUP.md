# Настройка qw2 для Vision LLM

## Проблема

qw2 CLI требует конфигурации авторизации для работы с API. Без неё Vision LLM classifier не работает.

## Решение

### 1. Настройка на хосте

```bash
# Установить qw2 CLI (если не установлен)
npm install -g @qwen-code/qwen-code

# Настроить авторизацию
qwen auth login

# Или использовать API ключ
export QWEN_API_KEY="your-api-key"
```

### 2. Конфигурация для Docker

Создайте файл `~/.qwen/settings.json`:

```json
{
  "auth": {
    "type": "api-key",
    "apiKey": "your-api-key"
  },
  "model": "qwen-max",
  "baseUrl": "https://api.qwen.ai/v1"
}
```

### 3. Монтирование в Docker Compose

```yaml
services:
  anticaptcha:
    image: anticaptcha:latest
    volumes:
      - ~/.qwen:/home/deploy/.qwen:ro  # Монтируем конфигурацию
    environment:
      - QWEN_API_KEY=${QWEN_API_KEY}  # Или через переменную окружения
```

### 4. Запуск с конфигурацией

```bash
# С монтированием конфигурации
docker run --rm \
  -v ~/.qwen:/home/deploy/.qwen:ro \
  -v "$(pwd):/app:ro" \
  anticaptcha:latest \
  python3 your_script.py

# С переменной окружения
docker run --rm \
  -e QWEN_API_KEY="your-api-key" \
  -v "$(pwd):/app:ro" \
  anticaptcha:latest \
  python3 your_script.py
```

## Альтернативы

### 1. Использовать только YOLO (без Vision LLM)

```python
from workers.classifiers.yolo import YOLOClassifier

classifier = YOLOClassifier()
result = classifier.classify_tiles(image_bytes, "cars", "3x3")
```

**Плюсы:**
- Не требует API ключей
- Работает офлайн
- Быстрее (0.1-0.3s)

**Минусы:**
- Ниже точность (60-70% vs 70-90%)
- Только для image CAPTCHA

### 2. Hybrid Classifier (рекомендуется)

```python
from workers.classifiers.yolo import HybridClassifier

classifier = HybridClassifier()
result = await classifier.classify_tiles(image_bytes, "cars", "3x3")
```

**Стратегия:**
- 70% запросов → YOLO (бесплатно, быстро)
- 30% запросов → Vision LLM (платно, точно)

**Экономия:**
- 70% API calls
- Средняя скорость: ~1.4s
- Средняя стоимость: ~$0.002/запрос

## Проверка работы

```bash
# Проверить qw2 CLI
docker run --rm -v ~/.qwen:/home/deploy/.qwen:ro anticaptcha:latest qwen --version

# Проверить Vision LLM
docker run --rm -v ~/.qwen:/home/deploy/.qwen:ro -v "$(pwd):/app:ro" anticaptcha:latest \
  python3 -c "from workers.classifiers.vision_llm import VisionLLMClassifier; print('OK')"
```

## Получение API ключа

1. Зарегистрироваться на https://qwen.ai
2. Создать API ключ в личном кабинете
3. Добавить в конфигурацию

## Стоимость

- qwen-max: ~$0.006 за 1K tokens
- Средний запрос CAPTCHA: ~500 tokens
- Стоимость одного решения: ~$0.003

## Рекомендации

**Для production:**
- Использовать Hybrid Classifier
- Настроить qw2 с API ключом
- Монтировать конфигурацию через Docker Compose

**Для разработки:**
- Использовать только YOLO
- Не требует API ключей
- Работает из коробки

**Для тестирования:**
- Создать тестовые изображения
- Проверить оба классификатора
- Сравнить точность и скорость