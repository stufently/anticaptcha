# Code Review Results - Vision LLM Classifier

## Codex Review

**ВЕРДИКТ: НЕ ПРИНИМАТЬ**

### 1. Уязвимость безопасности (Critical)
**File**: `workers/classifiers/vision_llm.py:134`
**Problem**: `--yolo` режим без sandbox позволяет prompt injection выполнять команды с правами worker и раскрыть секреты.

**Fix**: Использовать `--sandbox docker` или `--sandbox true` для изоляции.

### 2. Обработка ошибок (Critical)
**File**: `workers/classifiers/vision_llm.py:287`
**Problem**: Отсутствие CLI и исключения превращаются в `[]`, неотличимо от успешной классификации.

**Fix**: Возвращать специальный маркер ошибки или выбрасывать исключение.

### 3. Дублирование индексов (Critical)
**File**: `workers/classifiers/vision_llm.py:300`
**Problem**: Парсер не проверяет уникальность индексов. `[2, 2]` приведёт к двойному клику.

**Fix**: Удалять дубликаты через `list(set(indices))`.

## Claude Review

**ВЕРДИКТ: НЕ ПРИНИМАТЬ**

### 1. Timeout (Critical)
**File**: `workers/classifiers/vision_llm.py:154`
**Problem**: Нет `asyncio.wait_for` вокруг `process.communicate()`, может зависнуть навсегда.

**Fix**: Добавить timeout в Python asyncio.

### 2. Race condition (Critical)
**File**: `workers/classifiers/vision_llm.py:52,101`
**Problem**: Фиксированные имена временных файлов при параллельных вызовах.

**Fix**: Использовать уникальные имена файлов (UUID).

### 3. Обработка ошибок в solver (Critical)
**File**: `workers/solvers/recaptcha.py:242-266`
**Problem**: Пустой ответ `[]` считается успехом, нажимается verify.

**Fix**: Проверять успешность классификации перед нажатием verify.

## Исправления

Все 6 проблем будут исправлены в следующем коммите.