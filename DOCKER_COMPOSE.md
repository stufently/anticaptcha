# Docker Compose Deployment

Локальное развертывание AntiCAPTCHA сервиса с помощью Docker Compose.

## Быстрый старт

### 1. Базовый запуск

```bash
# Собрать образ
docker-compose build

# Запустить сервис
docker-compose up -d

# Проверить статус
docker-compose ps

# Посмотреть логи
docker-compose logs -f anticaptcha
```

### 2. Доступ к API

```bash
# Health check
curl http://localhost:8000/health

# API документация
open http://localhost:8000/docs

# Решить CAPTCHA
curl -X POST http://localhost:8000/api/v1/captcha/solve \
  -H "Content-Type: application/json" \
  -d '{
    "captcha_type": "recaptcha_v2",
    "page_url": "https://example.com",
    "site_key": "6Le..."
  }'
```

## Конфигурации

### 1. Только AntiCAPTCHA (по умолчанию)

```bash
docker-compose up -d
```

### 2. С Redis (кэширование)

```bash
docker-compose --profile with-redis up -d
```

### 3. С PostgreSQL (production)

```bash
docker-compose --profile with-postgres up -d
```

Измените `DATABASE_URL` в `docker-compose.yml`:
```yaml
environment:
  - DATABASE_URL=postgresql://anticaptcha:${POSTGRES_PASSWORD}@postgres:5432/anticaptcha
```

### 4. С Nginx (reverse proxy)

```bash
docker-compose --profile with-nginx up -d
```

### 5. Полный стек

```bash
docker-compose --profile with-redis --profile with-postgres --profile with-nginx up -d
```

## Управление

### Остановка

```bash
# Остановить все сервисы
docker-compose down

# Остановить и удалить volumes
docker-compose down -v
```

### Перезапуск

```bash
docker-compose restart anticaptcha
```

### Обновление

```bash
# Пересобрать образ
docker-compose build --no-cache

# Перезапустить с новым образом
docker-compose up -d --force-recreate
```

### Масштабирование

```bash
# Запустить 3 реплики
docker-compose up -d --scale anticaptcha=3
```

## Мониторинг

### Логи

```bash
# Все сервисы
docker-compose logs -f

# Только anticaptcha
docker-compose logs -f anticaptcha

# Последние 100 строк
docker-compose logs --tail=100 anticaptcha
```

### Статистика

```bash
# Использование ресурсов
docker stats anticaptcha

# Проверка здоровья
docker-compose ps
```

## Production Deployment

### 1. Создайте `.env` файл

```bash
DATABASE_URL=postgresql://user:password@postgres:5432/anticaptcha
LOG_LEVEL=INFO
WORKERS_COUNT=8
```

### 2. Используйте production values

Создайте `docker-compose.prod.yml`:

```yaml
version: '3.8'

services:
  anticaptcha:
    build:
      context: .
      dockerfile: Dockerfile
    image: your-registry.com/anticaptcha:1.0.0
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '4'
          memory: 8G
        reservations:
          cpus: '2'
          memory: 4G
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - LOG_LEVEL=${LOG_LEVEL}
      - WORKERS_COUNT=${WORKERS_COUNT}
    volumes:
      - anticaptcha-data:/app/data
      - anticaptcha-models:/app/models
    restart: always
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 3. Запустите production версию

```bash
docker-compose -f docker-compose.prod.yml up -d
```

## Troubleshooting

### Контейнер не стартует

```bash
# Проверить логи
docker-compose logs anticaptcha

# Проверить статус
docker-compose ps

# Перезапустить
docker-compose restart anticaptcha
```

### Проблемы с портами

```bash
# Проверить занятые порты
netstat -tulpn | grep -E '8000|6379|5432|80'

# Изменить порты в docker-compose.yml
```

### Проблемы с volumes

```bash
# Проверить volumes
docker volume ls | grep anticaptcha

# Удалить volumes (ВНИМАНИЕ: удалит все данные!)
docker-compose down -v
```

### Проблемы с сетью

```bash
# Проверить сеть
docker network ls | grep anticaptcha

# Пересоздать сеть
docker-compose down
docker-compose up -d
```

## Backup & Restore

### Backup

```bash
# Backup data volume
docker run --rm -v anticaptcha_anticaptcha-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/anticaptcha-data-backup.tar.gz -C /data .

# Backup models volume
docker run --rm -v anticaptcha_anticaptcha-models:/data -v $(pwd):/backup \
  alpine tar czf /backup/anticaptcha-models-backup.tar.gz -C /data .
```

### Restore

```bash
# Restore data volume
docker run --rm -v anticaptcha_anticaptcha-data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/anticaptcha-data-backup.tar.gz -C /data

# Restore models volume
docker run --rm -v anticaptcha_anticaptcha-models:/data -v $(pwd):/backup \
  alpine tar xzf /backup/anticaptcha-models-backup.tar.gz -C /data
```

## Security

### 1. Измените пароли по умолчанию

Отредактируйте `docker-compose.yml`:
```yaml
environment:
  - POSTGRES_PASSWORD=your-secure-password
```

### 2. Используйте secrets

Создайте `secrets.env`:
```bash
POSTGRES_PASSWORD=your-secure-password
API_KEY=your-api-key
```

Запустите с secrets:
```bash
docker-compose --env-file secrets.env up -d
```

### 3. Ограничьте доступ

Используйте firewall для ограничения доступа к портам:
```bash
# Разрешить только локальный доступ
sudo ufw allow from 127.0.0.1 to any port 8000
```

## Лицензия

MIT