# ScraperWikiX 

This code is a clone of the master branch of the [ScraperWiki repository on bitbucket](http://bitbucket.org/ScraperWiki/scraperwiki) forked with the intention of cutting it down to make it easier to install as a Personal ScraperWiki. 


## Backend deps

Relies on rossjones/swx-datastore (replaces the version removed from here)

## Notes to self.

. ./env-up.sh to setup required env vars

When setting up the django db to run on postgres, the migrations might fail at 024.  If they do then the quickest workaround is to remove the code in the forward() method of the migration, replace it with pass and then

    psql scraperwiki
    drop table model_vaults cascade;
    drop table model_vault_members;

