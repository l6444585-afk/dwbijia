"""
数据库迁移脚本 - 添加price_compare字段

迁移版本: 001
迁移日期: 2026-03-10
迁移说明: 为products表添加price_compare系统所需字段
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite


def upgrade():
    """升级数据库"""
    op.add_column('products', sa.Column('taobao_listed', sa.Float(), nullable=True, comment='淘宝到手价（Excel原始值）'))
    op.add_column('products', sa.Column('activity_deduct', sa.Float(), nullable=True, default=0, comment='活动立减'))
    op.add_column('products', sa.Column('coupon_share', sa.Float(), nullable=True, default=0, comment='消费券分摊额'))
    op.add_column('products', sa.Column('jingou_deduct', sa.Float(), nullable=True, default=0, comment='购物金抵扣额'))
    op.add_column('products', sa.Column('taobao_final', sa.Float(), nullable=True, comment='淘宝最终成本'))
    op.add_column('products', sa.Column('dewu_price', sa.Float(), nullable=True, comment='得物个人卖家价格'))
    op.add_column('products', sa.Column('dewu_net', sa.Float(), nullable=True, comment='得物扣佣后收入'))
    op.add_column('products', sa.Column('profit', sa.Float(), nullable=True, comment='差价利润'))
    op.add_column('products', sa.Column('buyers_count', sa.Integer(), nullable=True, comment='得物最近付款人数'))
    op.add_column('products', sa.Column('is_manual', sa.Integer(), nullable=True, default=0, comment='是否手动录入（0否1是）'))
    op.add_column('products', sa.Column('article_no', sa.String(100), nullable=True, comment='货号'))
    op.add_column('products', sa.Column('model', sa.String(100), nullable=True, comment='型号'))
    
    op.create_index('idx_article', 'products', ['article_no'])
    op.create_index('idx_profit', 'products', ['profit'])
    
    print("✓ 数据库迁移完成：添加price_compare字段")


def downgrade():
    """降级数据库"""
    op.drop_index('idx_profit', 'products')
    op.drop_index('idx_article', 'products')
    
    op.drop_column('products', 'model')
    op.drop_column('products', 'article_no')
    op.drop_column('products', 'is_manual')
    op.drop_column('products', 'buyers_count')
    op.drop_column('products', 'profit')
    op.drop_column('products', 'dewu_net')
    op.drop_column('products', 'dewu_price')
    op.drop_column('products', 'taobao_final')
    op.drop_column('products', 'jingou_deduct')
    op.drop_column('products', 'coupon_share')
    op.drop_column('products', 'activity_deduct')
    op.drop_column('products', 'taobao_listed')
    
    print("✓ 数据库回滚完成：删除price_compare字段")


if __name__ == "__main__":
    upgrade()
