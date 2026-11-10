# AntiCAPTCHA Helm Chart

Helm chart для развертывания AntiCAPTCHA сервиса в Kubernetes.

## Установка

### Через Helm

```bash
# Добавить репозиторий (если нужен)
helm repo add anticaptcha https://your-repo.com/charts

# Установить chart
helm install anticaptcha ./chart -n anticaptcha --create-namespace

# С кастомными values
helm install anticaptcha ./chart -f values-prod.yaml -n anticaptcha
```

### Через ArgoCD

1. Создать Application манифест:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: anticaptcha
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/your-org/anticaptcha.git
    targetRevision: main
    path: chart
  destination:
    server: https://kubernetes.default.svc
    namespace: anticaptcha
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

2. Применить:
```bash
kubectl apply -f argocd-application.yaml
```

## Конфигурация

### Основные параметры

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `replicaCount` | Количество реплик | `1` |
| `image.repository` | Docker образ | `anticaptcha` |
| `image.tag` | Тег образа | `latest` |
| `service.port` | Порт сервиса | `8000` |
| `resources.limits.cpu` | Лимит CPU | `2000m` |
| `resources.limits.memory` | Лимит памяти | `4Gi` |

### Worker

Воркер — отдельный Deployment, и он **не получает** `ANTICAPTCHA_ADMIN_TOKEN`,
даже если тот задан в общем `env`: воркер открывает браузер на страницах, которые
контролирует атакующий, поэтому админ-токен (credential только для API) в его
окружение не попадает.

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `worker.existingSecret` | Secret только для воркера; пусто — берётся общий `existingSecret` | `""` |
| `worker.heartbeatFile` | Файл, который воркер обновляет из своего event loop | `/tmp/worker-heartbeat` |
| `worker.livenessProbe.enabled` | `false` убирает и livenessProbe, и startupProbe воркера | `true` |
| `worker.livenessProbe.maxAgeSeconds` | Предельный возраст heartbeat, который считается живым | `300` |
| `worker.livenessProbe.periodSeconds` | Период livenessProbe | `30` |
| `worker.livenessProbe.timeoutSeconds` | Таймаут livenessProbe | `10` |
| `worker.livenessProbe.failureThreshold` | Порог срабатываний livenessProbe | `3` |
| `worker.startupProbe.periodSeconds` | Период startupProbe | `10` |
| `worker.startupProbe.timeoutSeconds` | Таймаут startupProbe | `10` |
| `worker.startupProbe.failureThreshold` | Порог startupProbe (бюджет 60 × 10 с = 600 с на загрузку моделей) | `60` |

Обе пробы выполняют `python -m workers.heartbeat --check --max-age <maxAgeSeconds>`.
Воркер пишет метку времени в `worker.heartbeatFile` (переменная
`ANTICAPTCHA_WORKER_HEARTBEAT_FILE`, интервал — `ANTICAPTCHA_WORKER_HEARTBEAT_INTERVAL`,
по умолчанию 10 с) из своего event loop, поэтому:

- `startupProbe` закрывает загрузку моделей: heartbeat стартует сразу после
  `setup_solvers()`, `initialDelaySeconds` не нужен;
- `livenessProbe` ловит зависший event loop и мёртвый Chromium (раньше упавший
  браузер оставался в кэше, и все URL-задачи падали до рестарта пода);
- `maxAgeSeconds` взят с запасом над `ANTICAPTCHA_TASK_TIMEOUT` (120 с), чтобы
  долгое решение задачи не выглядело смертью воркера.

```yaml
worker:
  existingSecret: anticaptcha-worker-secrets  # свой Secret, без админ-токена
  heartbeatFile: /tmp/worker-heartbeat
  livenessProbe:
    enabled: true
    maxAgeSeconds: 300
    periodSeconds: 30
```

### Persistence

```yaml
persistence:
  enabled: true
  storageClass: "standard"
  accessModes:
    - ReadWriteOnce
  size: 10Gi
```

### Ingress

```yaml
ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
  hosts:
    - host: anticaptcha.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: anticaptcha-tls
      hosts:
        - anticaptcha.example.com
```

### Environment Variables

```yaml
env:
  - name: DATABASE_URL
    value: "sqlite+aiosqlite:///./data/anticaptcha.db"
  - name: LOG_LEVEL
    value: "INFO"
  - name: WORKERS_COUNT
    value: "4"
```

## Production Deployment

### values-prod.yaml

```yaml
replicaCount: 3

image:
  repository: your-registry.com/anticaptcha
  tag: "1.0.0"

resources:
  limits:
    cpu: 4000m
    memory: 8Gi
  requests:
    cpu: 1000m
    memory: 2Gi

persistence:
  enabled: true
  storageClass: "fast-ssd"
  size: 50Gi

ingress:
  enabled: true
  className: "nginx"
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/rate-limit: "100"
  hosts:
    - host: anticaptcha.your-domain.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: anticaptcha-tls
      hosts:
        - anticaptcha.your-domain.com

autoscaling:
  enabled: true
  minReplicas: 3
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

### Установка production версии

```bash
helm install anticaptcha-prod ./chart -f values-prod.yaml -n anticaptcha-prod --create-namespace
```

## Обновление

```bash
# Обновить chart
helm upgrade anticaptcha ./chart -n anticaptcha

# С новыми values
helm upgrade anticaptcha ./chart -f values-prod.yaml -n anticaptcha
```

## Удаление

```bash
helm uninstall anticaptcha -n anticaptcha
```

## Мониторинг

### Проверка статуса

```bash
kubectl get pods -n anticaptcha
kubectl get svc -n anticaptcha
kubectl get ingress -n anticaptcha
```

### Логи

```bash
kubectl logs -f deployment/anticaptcha -n anticaptcha
```

### Метрики

```bash
# Port-forward для доступа к API
kubectl port-forward svc/anticaptcha 8000:8000 -n anticaptcha

# Проверка health
curl http://localhost:8000/health
```

## Troubleshooting

### Pod не стартует

```bash
kubectl describe pod <pod-name> -n anticaptcha
kubectl logs <pod-name> -n anticaptcha
```

### PVC не создается

```bash
kubectl get pvc -n anticaptcha
kubectl describe pvc <pvc-name> -n anticaptcha
```

### Ingress не работает

```bash
kubectl get ingress -n anticaptcha
kubectl describe ingress <ingress-name> -n anticaptcha
```

## Лицензия

MIT