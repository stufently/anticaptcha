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