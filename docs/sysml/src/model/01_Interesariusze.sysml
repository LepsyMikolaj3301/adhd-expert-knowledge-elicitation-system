package InteresariuszeElicytacji {
    doc /*
     * Interesariusze i ich potrzeby. Potrzeba to `concern` (ZAG-xx); wymagania, które na nią
     * odpowiadają, wskazują ją przez `frame` (02_Wymagania).
     *
     * Interesariusze to role, nie konkretne osoby. Ci, którzy sami korzystają z systemu
     * (ekspert, recenzent, inżynier wiedzy), są też aktorami (`:> Aktor`); pacjent i klinicysta
     * nie są. Deweloper (autor systemu) nie jest
     * interesariuszem modelu: wdrożenie i utrzymanie są poza zakresem.
     */

    private import BibliotekaElicytacji::*;

    // stakeholders
    package Interesariusze {
        part def Pacjent {
            doc /*
             * Interesariusz pośredni. Jego wypowiedzi (tekst pacjenta) inżynier wiedzy przerabia
             * na winietę, na którą odpowiadają eksperci. Pacjent nie korzysta z systemu.
             */
        }

        part def Ekspert :> Aktor {
            doc /*
             * Psychiatra lub psycholog. Odpowiada na przydzielone winiety, sprawdza korektę swoich
             * odpowiedzi. W kodzie: rola `expert`, aktor przepływu `assignee`.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/users/models.py"; }
        }

        part def Recenzent :> Ekspert {
            doc /*
             * Ekspert, który czyta, komentuje i ocenia odpowiedzi kolegi (aktor przepływu
             * `reviewer`). Nie jest osobnym typem konta. Aktorem jest przez Ekspert.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/reviews/access.py"; }
        }

        part def InzynierWiedzy :> Aktor {
            doc /*
             * Inżynier wiedzy, w aplikacji administrator (rola `admin`, aktor przepływu `admin`):
             * pisze i publikuje winiety, zaprasza i przydziela ekspertów, rozstrzyga recenzje,
             * ponawia nieudane zadania, zarządza bazą wiedzy.
             */
            @OdwolanieDoKodu { sciezka = "backend/app/users/models.py"; }
        }

        part def Klinicysta {
            doc /*
             * Użytkownik RAG kliniki: zadaje pytania kliniczne i dostaje odpowiedzi oparte na
             * dokumentach medycznych kliniki i na wiedzy eksperckiej. Nie loguje się do systemu
             * elicytacji.
             */
        }
    }

    private import Interesariusze::*;

    // =================================================================== needs (concerns)
    package Potrzeby {
        concern <'ZAG-01'> wiernoscWiedzy { subject s;
            doc /* Wiedza w bazie to słowa eksperta, sprawdzone przez niego po korekcie, a nie parafraza modelu językowego. */
            stakeholder inzynierWiedzy : InzynierWiedzy;
            stakeholder klinicysta : Klinicysta;
        }

        concern <'ZAG-02'> odpowiedziBezWplywu { subject s;
            doc /* Odpowiedź eksperta nie jest zabarwiona lekturą cudzych odpowiedzi ani zamysłem autora winiety. */
            stakeholder inzynierWiedzy : InzynierWiedzy;
        }

        concern <'ZAG-03'> malyNakladEksperta { subject s;
            doc /* Ekspert poświęca czas na wiedzę, nie na obsługę narzędzia. */
            stakeholder ekspert : Ekspert;
        }

        concern <'ZAG-04'> kontrolaNadBazaWiedzy { subject s;
            doc /* Inżynier wiedzy decyduje, co trafia do bazy wiedzy, i może to z niej usunąć. */
            stakeholder inzynierWiedzy : InzynierWiedzy;
        }

        concern <'ZAG-05'> prywatnoscEksperta { subject s;
            doc /* Dane ekspertów są chronione; w zgłoszeniach i w bazie wiedzy ekspert nie występuje z nazwiska (RODO). */
            stakeholder ekspert : Ekspert;
        }

        concern <'ZAG-06'> sladowalnosc { subject s;
            doc /* Każdą zmianę stanu i każdą jednostkę wiedzy da się odtworzyć do źródła: ekspert, winieta, cytat, decyzja. */
            stakeholder inzynierWiedzy : InzynierWiedzy;
            stakeholder klinicysta : Klinicysta;
        }

        concern <'ZAG-07'> ochronaDanychPacjenta { subject s;
            doc /* Z winiety ani z bazy wiedzy nie da się zidentyfikować pacjenta. */
            stakeholder pacjent : Pacjent;
        }

        concern <'ZAG-08'> wiedzaDlaRagKliniki { subject s;
            doc /*
             * Klinika może dołączyć wiedzę ekspercką do swojego RAG obok dokumentów medycznych,
             * bez przebudowy tego RAG i bez prawa zapisu do bazy wiedzy.
             */
            stakeholder klinicysta : Klinicysta;
        }
    }
}
