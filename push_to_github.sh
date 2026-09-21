#!/usr/bin/env bash
# ============================================================
# 一键推送到 GitHub
# ------------------------------------------------------------
# 用法：
#   1) 先在 GitHub 网页上创建一个**空仓库**（不要勾选 README / .gitignore / License）
#   2) 在本目录执行：
#        ./push_to_github.sh git@github.com:<你的用户名>/<仓库名>.git
#      或（用 HTTPS）：
#        ./push_to_github.sh https://github.com/<你的用户名>/<仓库名>.git
# ============================================================
set -euo pipefail

cd "$(dirname "$0")"

REMOTE_URL="${1:-}"

if [ -z "$REMOTE_URL" ]; then
  echo "❌ 缺少仓库地址"
  echo
  echo "用法: ./push_to_github.sh <GitHub 仓库地址>"
  echo
  echo "示例:"
  echo "  ./push_to_github.sh git@github.com:yourname/fund-analysis.git"
  echo "  ./push_to_github.sh https://github.com/yourname/fund-analysis.git"
  echo
  echo "提示：请先在 https://github.com/new 创建一个空仓库（不要初始化 README/License）。"
  exit 1
fi

# ---------- 推送前的安全兜底检查 ----------
echo "🔍 推送前安全检查..."
if git ls-files --error-unmatch .env >/dev/null 2>&1; then
  echo "❌ 危险：.env 已被纳入版本控制！已中止推送。"
  echo "   请执行：git rm --cached .env && git commit -m 'chore: 移除误提交的 .env'"
  exit 1
fi
if git ls-files | grep -qE "(^|/)(fund_analysis\.db|notification_config\.json|\.jwt_secret)$"; then
  echo "❌ 危险：检测到用户数据/密钥文件被纳入版本控制！已中止推送。"
  git ls-files | grep -E "(^|/)(fund_analysis\.db|notification_config\.json|\.jwt_secret)$"
  exit 1
fi
echo "✅ 未发现敏感文件被跟踪"

# ---------- SSH 连通性预检（代理/端口问题会给出可读的解法）----------
case "$REMOTE_URL" in
  git@*|ssh://*)
    SSH_HOST="$(printf '%s' "$REMOTE_URL" | sed -E 's#^ssh://([^@]*@)?##; s#^git@##; s#[:/].*##')"
    echo "🔍 检测 SSH 连通性（${SSH_HOST}）..."
    SSH_OUT="$(ssh -T -o BatchMode=yes -o ConnectTimeout=8 "git@$SSH_HOST" 2>&1 || true)"
    if printf '%s' "$SSH_OUT" | grep -q "successfully authenticated"; then
      echo "✅ SSH 认证正常"
    elif printf '%s' "$SSH_OUT" | grep -qE "Permission denied"; then
      echo "❌ SSH 密钥未被 GitHub 接受。"
      echo "   请把公钥添加到 https://github.com/settings/ssh/new"
      echo "   公钥内容："
      echo "     $(cat ~/.ssh/id_ed25519.pub 2>/dev/null || echo '(未找到 ~/.ssh/id_ed25519.pub)')"
      exit 1
    elif printf '%s' "$SSH_OUT" | grep -qE "Connection closed|Connection refused|port 22|Operation timed out|Network is unreachable"; then
      echo "❌ SSH 无法连接（常见原因：本地代理以 fake-IP 模式封锁了 22 端口）。"
      echo "   解法：把 GitHub 的 SSH 改走 443 端口，在 ~/.ssh/config 加入："
      echo "     Host github.com"
      echo "       HostName ssh.github.com"
      echo "       Port 443"
      echo "       User git"
      echo "   或改用 HTTPS 地址：./push_to_github.sh https://github.com/<用户>/<仓库>.git"
      exit 1
    else
      echo "ℹ️ 连通性预检未得出结论，继续尝试推送..."
    fi
    ;;
esac

# ---------- 配置远程并推送 ----------
if git remote get-url origin >/dev/null 2>&1; then
  echo "ℹ️  origin 已存在，更新为：$REMOTE_URL"
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "🚀 推送分支 $BRANCH 到 origin ..."
git push -u origin "$BRANCH"

echo
echo "✅ 完成！仓库地址：$REMOTE_URL"
