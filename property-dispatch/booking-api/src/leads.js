// leads.js — persistence for booking leads (Supabase PostgreSQL `leads` table).

import { createClient } from '@supabase/supabase-js';

/**
 * Server-side only: the service-role key bypasses RLS, so it must never be
 * shipped to the browser.
 */
export function supabaseLeadStore(url, serviceRoleKey) {
  const supabase = createClient(url, serviceRoleKey, { auth: { persistSession: false } });

  return {
    async insertLead({ address, formattedAddress, lat, lng, zoneName, baseMowRate }) {
      const { data, error } = await supabase
        .from('leads')
        .insert({
          address,
          formatted_address: formattedAddress,
          lat,
          lng,
          zone_name: zoneName,
          base_mow_rate: baseMowRate,
        })
        .select('id')
        .single();
      if (error) throw new Error(`Lead insert failed: ${error.message}`);
      return data;
    },
  };
}

export function leadStoreFromEnv(env = process.env) {
  if (!env.SUPABASE_URL || !env.SUPABASE_SERVICE_ROLE_KEY) {
    throw new Error('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set');
  }
  return supabaseLeadStore(env.SUPABASE_URL, env.SUPABASE_SERVICE_ROLE_KEY);
}
