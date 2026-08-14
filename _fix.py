from pathlib import Path
p = Path("tokenmon.py")
t = p.read_text(encoding="utf-8")
old = '_safe_print(f"[tokenmon] 已生成默认配置: {path}\n"
                    f"          请编辑 api_key/base_url 后重新运行。")'
new = '_safe_print("[tokenmon] 已生成默认配置: " + str(path) + "\\n          请编辑 api_key/base_url 后重新运行。")'
assert old in t, "pattern not found"
p.write_text(t.replace(old, new), encoding="utf-8")
print("fixed")
