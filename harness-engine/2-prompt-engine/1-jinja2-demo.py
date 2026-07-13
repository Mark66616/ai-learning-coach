from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template

# 模板目录相对于当前 Python 文件，而不是运行命令时所在的目录；
# 这样从项目根目录或测试目录执行时，都能稳定找到模板。
TEMPLATES_DIR = Path(__file__).parents[1] / "templates"

# FileSystemLoader 负责按文件名读取模板。
# StrictUndefined 让遗漏变量立刻报错，避免把 "{{ email_text }}" 原样发给模型。
# trim_blocks/lstrip_blocks 用于减少 if/for 产生的多余空行和缩进。
env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

# get_template 的参数是相对于 templates/ 的文件名；这里不传绝对路径。
template = env.get_template("email_classification.j2")

# render 的关键字参数会填充同名的 {{ 变量 }}。
# 列表会在模板的 for 循环中逐项访问，字典字段可写成 example.text。
prompt = template.render(
    email_text="系统提示您的账户存在异常登录，请尽快处理。",
    labels=["work", "personal", "spam"]
)

# 在调用模型前先打印或写入日志；这是排查变量缺失、标签拼错和格式问题的最快方式。
print("=== 最终 Prompt（无few-shot版本） ===")
print(prompt)
print("--"*30)

# 变量已经在一个字典中时，用 ** 解包填充；适合直接使用 JSONL 测试用例。
case = {
    "email_text": "会议室改到 A301",
    "labels": ["work", "personal", "spam"],
    "few_shot_examples": [
        {"text": "明天上午十点开项目会", "label": "work"},
        {"text": "恭喜中奖，点击链接领取奖品", "label": "spam"},
    ],
}

# 模板在任务子目录时，仍使用相对于 templates/ 的 POSIX 路径。
template2 = env.get_template("email_classification/v2.j2")

prompt2 = template2.render(**case)

print("=== 最终 Prompt（有few-shot版本） ===")
print(prompt2)
print("--"*30)

case2 = {
    "email_text": "会议室改到 A301",
    "labels": ["work", "personal", "spam"],
    "importances": ["P0", "P1", "P2", "P3", "P4", "P5"],
    "few_shot_examples": [
        {"text": "明天上午十点开项目会", "label": "work", "importance": "P2"},
        {"text": "恭喜中奖，点击链接领取奖品", "label": "spam", "importance": "P3"},
    ],
}
template3 = env.get_template("email_classification/v2.1.j2")

prompt3 = template3.render(**case2)

print("=== 最终 Prompt（有few-shot版本） ===")
print(prompt3)
print("--"*30)

# 仅用于本地快速实验的直接字符串模板；正式项目优先使用文件模板，便于版本管理。
quick_prompt = Template("将 {{ text }} 翻译成 {{ target_language }}。")
prompt4 = quick_prompt.render(text="Good morning", target_language="中文")
print("==== 快速验证 prompt 写法(类似日志占位符) ====")
print(prompt4)

if __name__ == "__main__":
    pass
