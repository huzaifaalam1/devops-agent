import pg from "pg";

export const dynamic = "force-dynamic";

export default async function Page() {
  const client = new pg.Client({
    connectionString: process.env.DATABASE_URL,
    connectionTimeoutMillis: 2000,
  });
  try {
    await client.connect();
    const result = await client.query("SELECT 1 AS ready");
    return <main>Database ready: {result.rows[0].ready}</main>;
  } finally {
    await client.end();
  }
}
