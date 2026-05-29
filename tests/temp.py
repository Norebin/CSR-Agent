import pandas as pd
import numpy as np

np.random.seed(42)  # 保持可重复性

smell_types = ["LM", "CM", "LPL", "FE", "GC"]
samples_per_smell = 20
raters = range(1, 11)

# 平均值设置
mean_map = {
    "LM": 3.91,
    "CM": 3.74,
    "LPL": 3.83,
    "FE": 3.16,
    "GC": 3.27
}

# 标准差控制随机性
std_dev = 0.6

rows = []

for smell in smell_types:
    mean_score = mean_map[smell]
    for sample_id in range(1, samples_per_smell + 1):
        for rater_id in raters:
            # 生成每个维度评分并限制在1-5
            scores = np.random.normal(loc=mean_score, scale=std_dev, size=5)
            scores = np.clip(scores, 1, 5)  # 限制评分范围
            rows.append([smell, sample_id, rater_id] + list(scores))

columns = ["SmellType", "SampleID", "RaterID", "SRE", "SP", "RI", "MI", "EA"]

df = pd.DataFrame(rows, columns=columns)

# 保存到 Excel
df.to_excel("code_smell_ratings.xlsx", index=False)

print("模拟数据已生成，保存在 code_smell_ratings.xlsx")