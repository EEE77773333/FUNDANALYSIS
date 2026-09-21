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
