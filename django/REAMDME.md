# django项目源码解析

## 基础介绍


### django目录

- apps: (导出AppConfig配置类和apps应用中心实例)
  - config.py:
    - AppConfig: 应用配置类（配置信息和模型）
  - registry.py:
    - Apps: 应用实例（可根据AppConfig注册app信息）
  - __init__.py:
- conf: (项目配置信息)
  - app_template:
  - locale:
  - project_template:
  - urls:
  - __init__.py: (导出LazySettings默认实例)
    - SettingsReference:
    - LazySettings:
    - Settings:
    - UserSettingsHolder:
  - global_settings.py: 全局默认配置信息
- contrib
- core: (项目核心功能)
  - cache:
  - checks: 校验包
  - files:
  - handlers:
  - mail:
  - management:
    - commands:
      - runserver.py: (runserver命令执行)
        - Command:
          -
    - __init__.py:
      - find_commands(): 查询commands子目录下的命令
      - load_command_class(): 动态导入Command类
      - get_commands(): 加载所有command信息（返回dict）
      - call_command(): 直接调用执行命令
      - ManagementUtility: 命令工具集类
      - execute_from_command_line() 调用执行命令行（ManagementUtility包装）
    - base.py:
      - CommandError: 命令异常类
      - OutputWrapper:
      - BaseCommand: 命令基类
        - get_version(): 默认返回django版本
        - create_parser(): 创建命令参数解析器
        - add_arguments(): 子类重写添加命令参数
        - add_base_argument(): 子类添加基础命令参数（）
        - print_help(): 打印命令参数解析
        - run_from_argv(): 命令运行入口（内部调用execute(), 结束关闭所有connection）
        - execute(): 命令内部调用执行（参数校验、系统检查、数据库迁移检查、handle()调用）
        - check(): 系统检查
        - check_migrations(): 数据库迁移检查
        - handle(): 命令内部真正逻辑
    - color.py:
    - sql.py:
    - templates.py:
    - utils.py:
  - serializers:
  - servers: 服务实现包
    - basehttp.py:
      - get_internal_wsgi_application():
  - __init__.py:
  - asgi.py:
  - exceptions.py:
  - paginator.py:
  - signals.py:
  - signging.py:
  - validators.py:
  - wsgi.py:
- db
  - backends:
  - migrations: 数据库迁移
    - operations:
    - __init__.py:
    - autodetector.py:
    - exceptions.py:
    - executor.py:
    - graph.py:
    - loader.py:
    - migraion.py:
      - Migration: 数据库迁移类
    - optimizer.py:
    - questioner.py:
    - recorder.py:
    - serializer.py:
    - state.py:
    - utils.py:
    - writer.py:
  - models:
  - __init__.py:
  - transaction.py:
  - utils.py:
- dispatch
- forms
- http
- middleware
- template
- templateargs
- test
- urls
- utils
- shortcuts.py:


## 核心功能

