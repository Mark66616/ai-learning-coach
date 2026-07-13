from pathlib import Path

import yaml
from jinja2 import Template, FileSystemLoader, StrictUndefined, Environment


def load_yaml(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


class PromptManager:
    def __init__(self, config_path: str):
        self.config = load_yaml(config_path)
        # 存放读取到的prompt文件模板
        self.templates = {}
        # 获取prompt文件存放的文件夹路径
        template_path = Path(__file__).parent[1] / "template" / ""
        self.env = Environment(
            loader=FileSystemLoader(template_path),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def load_template(self, template_name: str) -> None | Template:
        template = self.env.get_template(template_name)
        return Template(template)

    def get_template(self, task_name: str, version: str = None) -> Template:
        # 如果未指定版本，则使用默认版本
        if version is None:
            version = self.config[task_name]["current_version"]

        # 读取制定版本的 template 文件名
        template_file = self.config[task_name]["versions"][version]["template"]
        return self.load_template(f"{task_name}/{template_file}")

    def get_ab_variant(self, task_name: str) -> tuple[str, Template]:
        """A/B 测试：随机返回一个变体"""
        ab_config = self.config[task_name].get("ab_test", {})

        # 如果不激活 A/B 测试，则返回默认版本配置
        if not ab_config.get("active"):
            version = self.config[task_name]["current_version"]
            return version, self.get_template(task_name, version)

        import random
        # 随机的版本
        variants = ab_config["variants"]
        weights = [ab_config["traffic_split"][v] for v in variants]

        # random.choices(...) 默认只抽取 1 个，也可已返回多个
        # chosen_list = random.choices(variants, weights=weights,k=3)
        chosen = random.choices(variants, weights=weights)[0]
        return chosen, self.get_template(task_name, chosen)
