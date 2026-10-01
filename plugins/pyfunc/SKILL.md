---
name: pyfunc
description: 计算器与代码执行（外部插件 adapter 示例）：加/减/乘/除/指数
when_to_use: 用户需要精确计算时（不要心算，直接用工具）
---
# pyfunc 技能

工具：calc_add / calc_sub / calc_mul / calc_div / calc_pow。
1. 任何算术问题 → 直接调用对应工具，**不要把计算结果心算后写进回复**
2. 除法注意除数不为 0；结果保留合理小数位
3. 本插件演示 adapter：把外部格式插件（普通函数+register）适配成 LangChain 工具
