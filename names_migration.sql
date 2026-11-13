-- Run once in Supabase > SQL Editor, BEFORE uploading the new app.py. Safe to run more than once.
-- Adds first name and surname to each person, and fills them in when someone creates an account.
alter table profiles add column if not exists first_name text;
alter table profiles add column if not exists surname text;

create or replace function handle_new_user() returns trigger language plpgsql security definer set search_path=public as
$$
declare r text;
begin
  -- If you created the optional "invited" list earlier, honour it; otherwise everyone starts as a viewer.
  if to_regclass('public.invited') is not null then
    execute 'select role from public.invited where lower(email)=lower($1)' into r using new.email;
  end if;
  insert into profiles(id, email, role, first_name, surname)
  values (new.id, new.email, coalesce(r, 'viewer'),
          nullif(trim(new.raw_user_meta_data->>'first_name'), ''),
          nullif(trim(new.raw_user_meta_data->>'surname'), ''));
  return new;
end
$$;
