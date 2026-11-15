# Code Review Report - 2026-11-10

## Reviewers
- ✅ Claude Code
- ✅ Codex
- ⚠️ AGY (skill not found)

## Critical Issues Found & Fixed

### 1. 🔴 Security: API Key Creation Without Authentication
**Found by:** Claude + Codex  
**File:** `app/api/auth.py:56`  
**Issue:** `create_api_key` endpoint had no authentication, anyone could create API keys for any user  
**Fix:** Added `get_current_user` dependency, requires Bearer token. Admin can create for any user, regular users only for themselves.

### 2. 🔴 Security: Password Hashing Without Salt
**Found by:** Claude  
**File:** `app/api/auth.py:13-15`  
**Issue:** Passwords hashed with plain SHA-256, vulnerable to rainbow table attacks  
**Fix:** Added salt generation with `secrets.token_hex(16)`, hash format: `SHA256(salt:password)`

### 3. 🔴 Security: SSRF Vulnerability
**Found by:** Codex  
**File:** `workers/solvers/recaptcha.py:117`  
**Issue:** `page_url` passed to browser without validation, could access internal services  
**Fix:** Added URL validation:
- Block localhost (127.0.0.1, ::1, localhost)
- Block private IPs (10.x, 172.16-31.x, 192.168.x)
- Block cloud metadata endpoints (169.254.169.254)

### 4. 🔴 Deployment: Worker Not Started
**Found by:** Codex  
**Files:** `Dockerfile`, `docker-compose.yml`, `chart/templates/deployment.yaml`  
**Issue:** Only API server started, worker process never launched, tasks stay pending forever  
**Fix:** 
- Split docker-compose into `anticaptcha-api` + `anticaptcha-worker`
- Added separate worker deployment in Helm chart
- Worker runs `python -m workers.task_worker`

### 5. 🟡 Logic: Vision LLM Error Handling
**Found by:** Claude + Codex  
**File:** `workers/classifiers/vision_llm.py:225,273`  
**Issue:** Parse errors return `"{}"` instead of raising exception, silently treated as "no tiles"  
**Status:** ⚠️ Not fixed yet - requires more investigation

### 6. 🟡 Logic: hCaptcha Image Challenge Not Implemented
**Found by:** Codex  
**File:** `workers/solvers/hcaptcha.py:75`  
**Issue:** Image challenge ends with `NotImplementedError`  
**Status:** ⚠️ Not fixed yet - hCaptcha requires different approach

### 7. 🟡 Logic: YOLO Classifier Returns Wrong Objects
**Found by:** Codex  
**File:** `workers/classifiers/yolo.py:157`  
**Issue:** When target class not found, returns any detected objects instead of empty list  
**Status:** ⚠️ Not fixed yet - needs filtering logic

### 8. 🟡 Logic: reCAPTCHA Verify Click on Empty Response
**Found by:** Claude  
**File:** `workers/solvers/recaptcha.py:272-288`  
**Issue:** When classifier returns empty list, still clicks verify and returns success  
**Status:** ⚠️ Not fixed yet - needs proper error handling

## Fixed Issues Summary

| # | Issue | Severity | Status | Commit |
|---|-------|----------|--------|--------|
| 1 | API key auth bypass | 🔴 Critical | ✅ Fixed | a230b79 |
| 2 | Password salt missing | 🔴 Critical | ✅ Fixed | a230b79 |
| 3 | SSRF vulnerability | 🔴 Critical | ✅ Fixed | a230b79 |
| 4 | Worker not started | 🔴 Critical | ✅ Fixed | a230b79 |
| 5 | Vision LLM error handling | 🟡 Medium | ⚠️ Pending | - |
| 6 | hCaptcha not implemented | 🟡 Medium | ⚠️ Pending | - |
| 7 | YOLO wrong objects | 🟡 Medium | ⚠️ Pending | - |
| 8 | reCAPTCHA empty response | 🟡 Medium | ⚠️ Pending | - |

## Files Modified

```
app/api/auth.py              - Added auth, salt, admin flag
app/models/api_key.py        - Added password_salt, is_admin fields
workers/solvers/recaptcha.py - Added SSRF protection
docker-compose.yml           - Split into API + Worker
chart/templates/deployment.yaml - Added worker deployment
chart/templates/service.yaml - Point to API component
```

## Remaining Issues

### Priority 1 (Should Fix)
- Vision LLM error handling - errors should raise exceptions
- reCAPTCHA empty response - should not click verify

### Priority 2 (Nice to Have)
- hCaptcha image challenge implementation
- YOLO classifier filtering

## Testing Recommendations

1. **Security Testing:**
   - Try creating API key without auth → should fail
   - Try accessing localhost URL → should fail
   - Try accessing private IP → should fail

2. **Deployment Testing:**
   - Deploy with docker-compose → check both containers running
   - Deploy with Helm → check API + Worker pods
   - Submit task → verify worker processes it

3. **Integration Testing:**
   - Create user → create API key → submit task → get result
   - Test all CAPTCHA types

## Conclusion

**Critical security and deployment issues fixed.** Service is now safer to deploy.

**Remaining issues** are logic bugs that affect accuracy but not security. Can be fixed in follow-up commits.

**Commit:** `a230b79` - Fix critical security and deployment issues from code review