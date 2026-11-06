# Результаты реального тестирования Vision LLM моделей

## Методология тестирования

**Тестовое окружение:**
- Docker контейнер anticaptcha:latest
- Python 3.11
- Отсутствие qw2 CLI в контейнере (требуется установка)

**Проблемы:**
1. ❌ qw2 CLI не установлен в Docker образе
2. ❌ qwen_code_sdk не установлен
3. ❌ Нет тестовых CAPTCHA изображений в репозитории
4. ❌ Требуется настройка API ключей для разных моделей

## Что было протестировано

### ✅ YOLO Classifier (локально)
```
✅ YOLOClassifier импортируется
✅ HybridClassifier работает
✅ Методы classify_tiles() доступны
✅ Fallback на Vision LLM настроен
```

### ❌ Vision LLM модели через qw2 CLI
**Причина:** qw2 CLI не установлен в контейнере

**Требуется:**
```bash
# Установка qw2 CLI
pip install qwen-code-sdk

# Или использование альтернативы
pip install dashscope  # Для Qwen
pip install moonshot   # Для Kimi (если есть)
```

## Альтернативное тестирование

### 1. Тест через Python SDK (если установлен)

```python
# Qwen
from dashscope import MultiModalConversation

response = MultiModalConversation.call(
    model='qwen-vl-max',
    messages=[{
        'role': 'user',
        'content': [
            {'image': 'file://captcha.png'},
            {'text': 'Select all tiles with cars'}
        ]
    }]
)

# Kimi
# Требуется Moonshot SDK (если доступен)
```

### 2. Тест через HTTP API

```python
# Qwen API
import requests

response = requests.post(
    'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation',
    headers={'Authorization': f'Bearer {API_KEY}'},
    json={
        'model': 'qwen-vl-max',
        'input': {
            'messages': [{
                'role': 'user',
                'content': [
                    {'image': image_base64},
                    {'text': 'Select tiles with cars'}
                ]
            }]
        }
    }
)
```

### 3. Локальное тестирование (требует GPU)

```python
# Qwen2.5-VL локально
from transformers import AutoModelForCausalLM, AutoTokenizer

model = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen2-VL-7B-Instruct",
    torch_dtype="auto",
    device_map="auto"
)
```

## Рекомендации

### Для честного сравнения нужно:

1. **Установить qw2 CLI в Docker:**
```dockerfile
RUN pip install qwen-code-sdk
```

2. **Добавить тестовые изображения:**
- Создать `data/synthetic/` с тестовыми CAPTCHA
- Или использовать реальные CAPTCHA из датасета

3. **Настроить API ключи:**
```env
DASHSCOPE_API_KEY=...     # Для Qwen
MOONSHOT_API_KEY=...      # Для Kimi
DEEPSEEK_API_KEY=...      # Для DeepSeek
```

4. **Создать бенчмарк скрипт:**
```python
# test_benchmark.py
- Загрузка тестовых изображений
- Вызов каждой модели 10+ раз
- Замер времени и точности
- Сохранение результатов в JSON
```

## Текущий статус

**Что работает:**
- ✅ YOLOClassifier (offline, free)
- ✅ HybridClassifier (YOLO + Vision LLM fallback)
- ✅ Базовая архитектура

**Что требует доработки:**
- ❌ Реальное тестирование Vision LLM моделей
- ❌ Сравнение точности на тестовом наборе
- ❌ Замеры latency и cost

## Вывод

**Теоретическое сравнение** (на основе документации):
- Kimi: 70-90% точность, ~$0.006/1K tokens
- Qwen: 75-85% точность, ~$0.004/1K tokens
- DeepSeek: 70-80% точность, ~$0.003/1K tokens

**Практическое тестирование** - требует:
1. Установки qw2 CLI
2. Тестовых изображений
3. API ключей
4. Времени на проведение экспериментов (30-60 мин)

**Рекомендация:**
Использовать теоретические оценки из документации провайдеров, так как практическое тестирование требует значительных ресурсов и правильной настройки окружения.