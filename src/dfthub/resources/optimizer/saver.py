import json
import numpy as np


def convert_to_serializable(obj):
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, dict):
        return {key: convert_to_serializable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [convert_to_serializable(item) for item in obj]
    return obj


def save_dict_to_json(result_dict, filename="results.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(convert_to_serializable(result_dict), f, ensure_ascii=False, indent=4)
    print(f"结果已保存到 {filename}")
