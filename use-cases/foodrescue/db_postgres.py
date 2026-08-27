"""FoodRescue AI PostgreSQL Repository Alias.

Exposes PostgresRepository pointing directly to SupabaseRepository
for flexible naming conventions across deployment and local configurations.
"""

from db_supabase import SupabaseRepository

# PostgresRepository alias
PostgresRepository = SupabaseRepository

__all__ = ["PostgresRepository", "SupabaseRepository"]
