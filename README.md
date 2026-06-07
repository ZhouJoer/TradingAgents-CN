# TradingAgents-CN Personal Fork

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/Version-v1.0.1-green.svg)](./VERSION)
[![Original](https://img.shields.io/badge/Original-TauricResearch%2FTradingAgents-orange.svg)](https://github.com/TauricResearch/TradingAgents)

这是我基于 [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) 继续 fork 的个人学习项目。项目核心来自 [Tauric Research](https://github.com/TauricResearch) 团队开源的 [TradingAgents](https://github.com/TauricResearch/TradingAgents)，并吸收了 TradingAgents-CN 对中文场景、A 股数据源、LLM 配置和 Web 化体验的增强。

本仓库主要用于学习、研究和技术交流，帮助我理解多智能体协作、LLM 驱动的金融研究流程、数据源集成、报告生成和工程化部署。项目不提供任何实盘交易指令，也不构成投资建议。

## 项目定位

- 个人 fork，不代表原项目或上游维护者的官方版本。
- 面向学习交流、代码阅读、实验验证和二次开发记录。
- 保留并尊重上游项目的版权声明、许可证要求和贡献来源。
- 所有投资相关输出仅作为研究样例，不能作为买卖依据。

## 简要介绍

TradingAgents 是一个多智能体交易研究框架，通过基本面、技术面、新闻、情绪、研究员辩论、交易员决策和风险管理等角色协作，模拟较完整的金融研究流程。

TradingAgents-CN 在此基础上做了中文化和工程化增强，包括：

- 中文界面与中文报告输出
- A 股/港股/美股等市场分析支持
- 多 LLM 提供商与自定义端点配置
- FastAPI + Vue 3 的 Web 架构
- MongoDB、Redis、Docker 等部署与缓存能力
- 数据同步、报告导出、分析记录等增强功能

## 我的改进方向

这个 fork 会围绕“更适合个人学习和可复现实验”逐步改进：

- 梳理和精简文档，让安装、配置、数据同步和常见问题更容易理解。
- 跟踪上游更新，选择性吸收稳定、清晰、适合本项目目标的改动。
- 改进数据源适配和错误提示，减少学习过程中的环境配置阻力。
- 优化提示词、智能体流程和报告结构，便于观察多智能体分析过程。
- 增加必要的测试、日志和调试说明，提高代码阅读和二次开发体验。
- 保持项目边界清晰，避免把学习项目包装成投资服务或商业产品。

## 使用与文档

建议先阅读以下文档：

- [v1.0.1 使用手册](./docs/guides/v1.0.1-user-manual.md)
- [v1.0.1 发布说明](./docs/releases/v1.0.1-release-notes.md)
- [升级指南](./docs/releases/upgrade-guide.md)
- [完整更新日志](./docs/releases/CHANGELOG.md)
- [文档目录](./docs/)

在分析股票前，请先完成必要的数据源配置和股票数据同步，否则分析结果可能不完整或出现数据错误。

## 上游与致谢

感谢 [Tauric Research](https://github.com/TauricResearch) 团队开源 [TradingAgents](https://github.com/TauricResearch/TradingAgents)，为多智能体金融研究提供了清晰而有启发性的框架基础。

感谢 [TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) 项目在中文化、A 股支持、Web 化、数据源集成和部署体验上的持续改进。本 fork 的学习和实验工作建立在这些上游贡献之上。

也感谢所有为相关项目提交代码、文档、问题反馈和实践经验的开源社区成员。

## 许可证与版权

本仓库继承并遵守上游项目的许可证与版权要求。请在使用、修改、分发或商业化前仔细阅读：

- [LICENSE](./LICENSE)
- [COPYRIGHT.md](./COPYRIGHT.md)
- [LICENSING.md](./LICENSING.md)
- [ACKNOWLEDGMENTS.md](./ACKNOWLEDGMENTS.md)

如上游文件中对部分目录或组件有额外授权要求，请以上游许可证和版权说明为准。

## 风险提示

本项目仅用于研究和教育目的，不构成投资建议。

- AI 模型输出可能存在事实错误、遗漏或过度推断。
- 金融市场受多种因素影响，历史数据和模型分析不能保证未来结果。
- 任何投资决策都应由使用者独立判断，并自行承担风险。
