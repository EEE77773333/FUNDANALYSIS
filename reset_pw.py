#!/usr/bin/env python3
from core.db import init_db; init_db()
from core.auth import AuthManager
from core.user_repo import UserRepo

repo = UserRepo()
user = repo.get_by_email("admin@fund.local")
if user:
    repo.update_password(user["id"], AuthManager.hash_password("新密码写这里"))
    print("密码已修改")
else:
    print("用户未找到")
