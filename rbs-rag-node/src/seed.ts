import { PrismaClient } from '@prisma/client';
import crypto from 'crypto';

async function seed() {
  if (!process.env.DATABASE_URL) {
    process.env.DATABASE_URL = 'file:./dev.db';
  }

  const prisma = new PrismaClient();

  const existing = await prisma.tenant.findMany();
  if (existing.length > 0) {
    console.log(`Already have ${existing.length} tenant(s). Skipping seed.`);
    await prisma.$disconnect();
    return;
  }

  const apiKey = `rbs_rag_sk_${crypto.randomBytes(16).toString('hex')}`;

  await prisma.tenant.create({
    data: {
      tenantId: 'demo',
      name: 'Demo Tenant',
      apiKey,
      status: 'active',
      subscriptionTier: 'basic',
      monthlyFee: 299,
      llmProvider: 'openai',
      llmModel: 'gpt-4o-mini',
      llmApiKey: process.env.LLM_API_KEY || 'set-your-openai-api-key',
      embeddingProvider: 'hash',
      embeddingModel: 'BAAI/bge-small-en-v1.5',
      embeddingDimensions: 384,
    },
  });

  console.log(`Created demo tenant:`);
  console.log(`  tenant_id: demo`);
  console.log(`  api_key: ${apiKey}`);
  console.log(`  dashboard: http://localhost:3001`);

  await prisma.$disconnect();
}

seed().catch(err => {
  console.error('Seed failed:', err);
  process.exit(1);
});
