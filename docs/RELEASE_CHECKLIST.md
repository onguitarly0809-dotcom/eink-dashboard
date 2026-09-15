# 发布检查清单

## 发布前检查

- [ ] 未提交任何本地计划文件
- [ ] 未提交任何日志、缓存、预览图或生成的二进制文件
- [ ] 未提交任何环境变量文件或访问凭证
- [ ] 未提交任何本机绝对路径
- [ ] 未提交任何个人身份信息、账号信息或私人调试记录
- [ ] `README.md`、`SECURITY.md`、`docs/CONFIGURATION.md` 均为最新
- [ ] `requirements.txt` 与实际依赖一致
- [ ] `.gitignore` 覆盖所有运行时产物
- [ ] `python -m compileall -q dashboard_serial` 通过
- [ ] `node --check dashboard_serial/web/app.js` 通过
- [ ] 敏感信息扫描通过

## 建议的发布流程

1. 从干净副本创建仓库。
2. 复核 `.gitignore`。
3. 运行语法检查。
4. 运行敏感信息扫描。
5. 提交初始版本。
6. 在 GitHub 上创建仓库。
7. 配置远程地址。
8. 推送到 GitHub。
