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

SSRF-guard воркера проверяет только `page_url` задачи. Страница, загруженная в
режиме `page`, может редиректом, скриптом или WebSocket обратиться к внутренним
адресам, а DNS-rebinding guard тоже не закрывает. Эту границу держит egress
NetworkPolicy воркера — см. раздел [NetworkPolicy воркера](#networkpolicy-воркера).

Если `worker.existingSecret` пуст, воркер подключает общий Secret
(`existingSecret`) целиком через `envFrom`. Ключ `ANTICAPTCHA_ADMIN_TOKEN` из него
перекрывается явной записью `env` с пустым значением (запись `env` главнее
`envFrom`), остальные ключи доходят до воркера. Чтобы воркер не видел вообще
ничего лишнего из общего Secret, задай ему отдельный —
`worker.existingSecret: anticaptcha-worker-secrets`.

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

### NetworkPolicy воркера

`networkPolicy.enabled: true` создаёт NetworkPolicy
`<release>-anticaptcha-worker-egress` на поды воркера (`policyTypes: [Egress]`).
Включать рекомендуется, если CNI кластера применяет NetworkPolicy (у k3s это
встроенный kube-router; Calico и Cilium тоже). Без такого CNI объект создастся,
но ничего не ограничит. По умолчанию политика выключена, чтобы обновление чарта
не меняло сетевое поведение существующих установок.

Политика разрешает воркеру только:

- DNS (UDP/TCP 53) к подам `k8s-app: kube-dns` в namespace `kube-system`
  (`networkPolicy.dns`; при NodeLocal DNSCache или другом DNS поправь селекторы
  или добавь правило в `extraEgress`);
- IPv4 `0.0.0.0/0` кроме частных, shared (100.64.0.0/10), loopback, link-local
  (169.254.0.0/16, в том числе metadata облака 169.254.169.254),
  документационных, multicast и зарезервированных диапазонов;
- IPv6 `::/0` кроме loopback, unique local (fc00::/7), link-local (fe80::/10),
  IPv4-mapped, NAT64, 6to4/Teredo, документационных и multicast — только при
  `networkPolicy.ipv6.enabled: true`. Без этого IPv6-egress запрещён целиком, что
  строже; включай в dual-stack кластерах.

Внутри кластера воркеру ничего не нужно: с API он общается через SQLite на общем
томе, LLM-эндпоинт публичный. Прокси задач и LLM внутри кластера — через
`extraEgress`.

Ограничения. Публичные адреса нод и Kubernetes API в частные диапазоны не
попадают — их добавь в `ipv4.extraExcept`/`ipv6.extraExcept` (CIDR своего
семейства, иначе шаблон завершится ошибкой). Но трафик пода к **своей** ноде
многие CNI пропускают независимо от политики (так допускает спецификация
NetworkPolicy), поэтому сервисы на `hostNetwork`/`hostPort` ноды воркера
`except` может не закрыть: не держи на нодах открытых без аутентификации
сервисов или выноси воркер на отдельные ноды.

| Параметр | Описание | По умолчанию |
|----------|----------|--------------|
| `networkPolicy.enabled` | Создать egress NetworkPolicy воркера | `false` |
| `networkPolicy.dns.namespaceSelector` | Namespace кластерного DNS | `matchLabels: {kubernetes.io/metadata.name: kube-system}` |
| `networkPolicy.dns.podSelector` | Поды кластерного DNS | `matchLabels: {k8s-app: kube-dns}` |
| `networkPolicy.dns.ports` | Порты DNS | UDP 53, TCP 53 |
| `networkPolicy.ipv4.cidr` | Разрешённый IPv4-диапазон | `0.0.0.0/0` |
| `networkPolicy.ipv4.except` | Исключения из него (замена списка целиком) | частные и спец-диапазоны, см. `values.yaml` |
| `networkPolicy.ipv4.extraExcept` | Дополнительные IPv4-исключения (добавляются к `except`) | `[]` |
| `networkPolicy.ipv6.enabled` | Разрешить публичный IPv6 | `false` |
| `networkPolicy.ipv6.cidr` | Разрешённый IPv6-диапазон | `::/0` |
| `networkPolicy.ipv6.except` | Исключения из него | loopback, ULA, link-local и др., см. `values.yaml` |
| `networkPolicy.ipv6.extraExcept` | Дополнительные IPv6-исключения | `[]` |
| `networkPolicy.extraEgress` | Дополнительные egress-правила, добавляются как есть | `[]` |

```yaml
networkPolicy:
  enabled: true
  ipv4:
    extraExcept:
      - 198.51.100.7/32   # публичный адрес ноды / API-сервера
  extraEgress:
    - to:
        - podSelector:
            matchLabels:
              app: egress-proxy
      ports:
        - protocol: TCP
          port: 3128
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