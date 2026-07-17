import { PrismaClient } from '@prisma/client';

export class AdminStore {
  private prisma: PrismaClient;

  constructor(prisma: PrismaClient) {
    this.prisma = prisma;
  }

  async listTenants(): Promise<any[]> {
    return this.prisma.tenant.findMany({ orderBy: { createdAt: 'desc' } });
  }

  async getTenant(tenantId: string): Promise<any | null> {
    return this.prisma.tenant.findUnique({ where: { tenantId } });
  }

  async getTenantByApiKey(apiKey: string): Promise<any | null> {
    return this.prisma.tenant.findUnique({ where: { apiKey } });
  }

  async upsertTenant(data: any): Promise<void> {
    const { tenantId, ...rest } = data;
    await this.prisma.tenant.upsert({
      where: { tenantId },
      update: rest,
      create: data,
    });
  }

  async deleteTenant(tenantId: string): Promise<void> {
    // Clean up in order
    await this.prisma.sessionTurn.deleteMany({ where: { tenantId } });
    await this.prisma.chunk.deleteMany({ where: { tenantId } });
    await this.prisma.document.deleteMany({ where: { tenantId } });
    await this.prisma.activityLog.deleteMany({ where: { tenantId } });
    await this.prisma.tenant.delete({ where: { tenantId } });
  }

  async logActivity(
    tenantId: string,
    level: string,
    operation: string,
    message: string,
    details?: any,
    traceback?: string
  ): Promise<void> {
    await this.prisma.activityLog.create({
      data: {
        tenantId,
        level,
        operation,
        message,
        details: details ? JSON.stringify(details) : null,
        traceback,
      },
    });
  }

  async getActivityLogs(tenantId?: string, level?: string, limit = 100): Promise<any[]> {
    const where: any = {};
    if (tenantId) where.tenantId = tenantId;
    if (level) where.level = level;
    return this.prisma.activityLog.findMany({
      where,
      orderBy: { createdAt: 'desc' },
      take: limit,
    });
  }
}
