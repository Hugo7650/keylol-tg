import asyncio
import logging
import os
import signal
import sys
from config import Config
from clients.forum_client import ForumClient
from clients.telegram_client import TelegramClient
from services.scheduler import TaskScheduler
from services.post_service import PostService

class KeylolTelegramApp:
    """主应用程序"""

    SHUTDOWN_TIMEOUT = 5
    
    def __init__(self):
        self.config = Config()
        self.forum_client = None
        self.telegram_client = None
        self.scheduler: TaskScheduler | None = None
        self.post_service : PostService
        self.work_dir = 'data'
        self.logger = self._setup_logging()
        self._should_exit = asyncio.Event()
        self._main_task = None
        self._stop_task = None
        self._exit_requested = False
        self._loop = None
    
    def _setup_logging(self) -> logging.Logger:
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.work_dir + '/keylol-tg.log', encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        return logging.getLogger(__name__)
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        self.logger.info(f"收到信号 {signum}，准备退出...")
        if self._exit_requested:
            os._exit(128 + signum)
        self._exit_requested = True
        if self._loop and self._main_task:
            self._loop.call_soon_threadsafe(self._main_task.cancel)
    
    async def start(self):
        """启动应用"""
        self._loop = asyncio.get_running_loop()
        self._main_task = asyncio.current_task()
        previous_handlers = {
            sig: signal.signal(sig, self._signal_handler)
            for sig in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            # 验证配置
            if not self.config.validate():
                self.logger.error("配置验证失败，请检查环境变量")
                return False
            
            self.logger.info("启动 Keylol Telegram 应用...")
            
            # 初始化各个组件
            await self._initialize_components()
            
            # 启动调度器
            if self.scheduler:
                self.scheduler.start()
            
            self.logger.info("应用启动成功，开始监控...")
            
            await self.post_service.check_and_send_new_posts()
            
            # 保持运行
            await self._keep_running()
            
        except asyncio.CancelledError:
            if not self._exit_requested:
                raise
        except Exception as e:
            self.logger.error(f"应用启动失败: {e}")
            return False
        finally:
            try:
                await self.stop()
            finally:
                for sig, handler in previous_handlers.items():
                    signal.signal(sig, handler)
    
    async def _initialize_components(self):
        """初始化各个组件"""
        # 初始化论坛客户端
        self.forum_client = ForumClient(
            self.config.forum_base_url,
            self.config.forum_username,
            self.config.forum_password,
            work_dir=self.work_dir,
            async_timeout=self.config.forum_async_timeout,
            request_retries=self.config.forum_request_retries,
            retry_backoff=self.config.forum_retry_backoff,
        )
        
        # 初始化Telegram客户端
        self.telegram_client = TelegramClient(
            self.config.telegram_api_id,
            self.config.telegram_api_hash,
            self.config.telegram_bot_token,
            work_dir=self.work_dir
        )
        await self.telegram_client.start()
        
        # 初始化帖子服务
        self.post_service = PostService(
            self.forum_client,
            self.telegram_client,
            self.config.telegram_channel_id,
            self.config.telegram_admin_id,
            self.config.max_posts_per_check,
            work_dir=self.work_dir,
        )
        
        # 设置相互引用
        self.telegram_client.set_post_service(self.post_service)
        
        # 初始化调度器
        self.scheduler = TaskScheduler(asyncio.get_running_loop())
        
        # 添加定时任务
        self.scheduler.add_job(
            func=self.post_service.check_and_send_new_posts,
            interval=self.config.check_interval,
            job_id="check_posts"
        )
        
        # 尝试初始登录
        try:
            await self.forum_client.async_login()
            await self.telegram_client.send_admin_notification(
                self.config.telegram_admin_id,
                "Keylol Telegram 应用已启动"
            )
        except Exception as e:
            await self.telegram_client.send_admin_notification(
                self.config.telegram_admin_id,
                f"应用启动，但论坛登录失败: {str(e)}"
            )
    
    async def _keep_running(self):
        """保持应用运行"""
        await self._should_exit.wait()
    
    async def stop(self):
        """停止应用"""
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._shutdown())
        await asyncio.shield(self._stop_task)

    async def _shutdown_step(self, name, operation):
        try:
            async with asyncio.timeout(self.SHUTDOWN_TIMEOUT):
                await operation()
        except TimeoutError:
            self.logger.warning("%s超时，继续退出", name)
        except Exception:
            self.logger.exception("%s失败，继续退出", name)

    async def _shutdown(self):
        self.logger.info("正在停止应用...")
        try:
            if self.scheduler:
                await self._shutdown_step("停止任务调度器", self.scheduler.stop)
            if self.telegram_client:
                await self._shutdown_step(
                    "发送停止通知",
                    lambda: self.telegram_client.send_admin_notification(
                        self.config.telegram_admin_id, "Keylol Telegram 应用已停止"
                    ),
                )
                await self._shutdown_step("停止 Telegram 客户端", self.telegram_client.stop)
            if self.forum_client:
                await self._shutdown_step("关闭论坛客户端", self.forum_client.aclose)
        finally:
            self._should_exit.set()
            self.logger.info("应用已停止")

async def main():
    """主函数"""
    app = KeylolTelegramApp()
    await app.start()

if __name__ == "__main__":
    asyncio.run(main())
